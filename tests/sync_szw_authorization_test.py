from __future__ import annotations

import base64
import io
import json
import logging
import subprocess
import sys
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_szw_authorization as sync_szw  # noqa: E402
from _ops import OpsError  # noqa: E402


def jwt(payload: object, *, header: object | None = None) -> str:
    def encode(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return ".".join(
        [
            encode({"alg": "HS256"} if header is None else header),
            encode(payload),
            base64.urlsafe_b64encode(bytes(32)).decode().rstrip("="),
        ]
    )


class AuthorizationValidationTest(unittest.TestCase):
    def test_accepts_raw_and_prefixed_jwt_without_returning_claims(self):
        token = jwt({"exp": 4_000_000_000, "sub": "private-subject"})
        self.assertEqual(sync_szw.validated_authorization(token), f"Wechat {token}")
        self.assertEqual(sync_szw.validated_authorization(f"Wechat {token}"), f"Wechat {token}")

    def test_rejects_invalid_expired_and_header_injection_without_secret_details(self):
        cases = [
            "",
            "private-invalid-token",
            "a.b.c",
            "Wechat a.b.c.d",
            "Bearer " + jwt({"exp": 4_000_000_000}),
            jwt({"exp": 4_000_000_000}) + "\r\nX-Leak: private-subject",
            jwt({"exp": 4_000_000_000}) + "\n",
            jwt({"exp": 4_000_000_000}) + "\\_",
            jwt({"sub": "private-subject"}),
            jwt({"exp": True}),
            jwt({"exp": "4000000000"}),
            jwt({"exp": float("nan")}),
            jwt({"exp": float("inf")}),
            jwt({"exp": 1}),
            jwt(["private-subject"]),
            jwt({"exp": 4_000_000_000}, header={"alg": "none"}),
            jwt({"exp": 4_000_000_000}, header=["private-subject"]),
            "x" * (sync_szw.MAX_AUTHORIZATION_LENGTH + 1),
        ]
        for candidate in cases:
            with self.subTest(kind=cases.index(candidate)):
                with self.assertRaises(OpsError) as caught:
                    sync_szw.validated_authorization(candidate)
                self.assertNotIn("private-subject", str(caught.exception))
                self.assertNotIn("private-invalid-token", str(caught.exception))

    def test_pool_requires_three_distinct_valid_accounts(self):
        candidates = [jwt({"exp": 4_000_000_000, "sub": f"private-subject-{n}"}) for n in range(3)]
        self.assertEqual(
            json.loads(sync_szw.validated_pool(json.dumps(candidates))),
            [f"Wechat {token}" for token in candidates],
        )
        invalid_pools = [
            "not-json",
            json.dumps(candidates[:2]),
            json.dumps(candidates + candidates[:1]),
            json.dumps([*candidates[:2], 5]),
            json.dumps([*candidates[:2], candidates[0]]),
            json.dumps([*candidates[:2], jwt({"exp": 4_000_000_000})]),
            json.dumps([*candidates[:2], jwt({"exp": 1, "sub": "private-expired"})]),
            json.dumps(
                [*candidates[:2], jwt({"exp": 4_000_000_000, "openid": "private-subject-0"})]
            ),
            json.dumps(
                [*candidates[:2], jwt({"exp": 4_000_000_000, "openid": " private-subject-0 "})]
            ),
        ]
        for index, candidate in enumerate(invalid_pools):
            with self.subTest(kind=index), self.assertRaises(OpsError) as caught:
                sync_szw.validated_pool(candidate)
            self.assertNotIn("private-subject", str(caught.exception))


class AuthorizationTransportTest(unittest.TestCase):
    def setUp(self):
        tokens = [jwt({"exp": 4_000_000_000, "sub": f"private-subject-{n}"}) for n in range(3)]
        self.token = tokens[0]
        self.authorization = f"Wechat {self.token}"
        self.pool_json = json.dumps(tokens)
        self.canonical_pool = sync_szw.validated_pool(self.pool_json)
        self.remote = {
            "host": "example.invalid",
            "port": "22",
            "username": "deploy",
            "repository_path": "/srv/airflow repo",
        }

    def test_streams_only_on_stdin_and_requires_verified_success(self):
        response = subprocess.CompletedProcess([], 0, json.dumps(sync_szw.SUCCESS_RESULT), "")
        with (
            patch.object(sync_szw, "airflow_remote", return_value=self.remote),
            patch.object(sync_szw.subprocess, "run", return_value=response) as run,
            patch.dict(
                sync_szw.os.environ,
                {
                    sync_szw.VARIABLE_NAME: self.pool_json,
                    sync_szw.LEGACY_VARIABLE_NAME: self.authorization,
                },
            ),
        ):
            result = sync_szw.sync(self.pool_json)
        command = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertNotIn(self.token, " ".join(command))
        self.assertNotIn(sync_szw.VARIABLE_NAME, options["env"])
        self.assertNotIn(sync_szw.LEGACY_VARIABLE_NAME, options["env"])
        self.assertEqual(options["input"], self.canonical_pool)
        self.assertEqual(options["timeout"], sync_szw.SYNC_TIMEOUT_SECONDS)
        self.assertTrue(options["capture_output"])
        self.assertFalse(options["check"])
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("PreferredAuthentications=publickey", command)
        self.assertEqual(result, sync_szw.SUCCESS_RESULT)
        self.assertNotIn(self.token, json.dumps(result))

    def test_subprocess_failures_do_not_disclose_output_or_exception_details(self):
        failures = [
            subprocess.CompletedProcess([], 1, self.authorization, "private-subject"),
            subprocess.CompletedProcess([], 0, json.dumps({"ok": True}), self.authorization),
            subprocess.CompletedProcess(
                [],
                1,
                json.dumps({"error": "gba_probe_failed", "unsafe": self.authorization}),
                self.authorization,
            ),
            subprocess.TimeoutExpired(
                ["ssh", self.authorization],
                150,
                output=self.authorization,
                stderr="private-subject",
            ),
            OSError(self.authorization),
        ]
        for index, failure in enumerate(failures):
            with self.subTest(kind=index):
                options = (
                    {"side_effect": failure}
                    if isinstance(failure, Exception)
                    else {"return_value": failure}
                )
                stdout, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.object(sync_szw, "airflow_remote", return_value=self.remote),
                    patch.object(sync_szw.subprocess, "run", **options),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                    self.assertRaises(OpsError) as caught,
                ):
                    sync_szw.sync(self.pool_json)
                combined = str(caught.exception) + stdout.getvalue() + stderr.getvalue()
                self.assertNotIn(self.token, combined)
                self.assertNotIn("private-subject", combined)

    def test_invalid_token_never_starts_transport(self):
        with patch.object(sync_szw.subprocess, "run") as run, self.assertRaises(OpsError):
            sync_szw.sync("invalid")
        run.assert_not_called()


class RemoteRotationTest(unittest.TestCase):
    def run_remote(self, *, fail_probe: int | None = None, readback_matches: bool = True):
        authorizations = [
            "Wechat " + jwt({"exp": 4_000_000_000, "sub": f"private-subject-{n}"}) for n in range(3)
        ]
        candidate = json.dumps(authorizations, separators=(",", ":"))
        old_values = {
            sync_szw.VARIABLE_NAME: "previous-protected-pool",
            sync_szw.LEGACY_VARIABLE_NAME: "previous-protected-value",
        }
        state = {"stored": dict(old_values), "writes": 0, "requests": [], "rollbacks": 0}

        class FakeKey:
            def __eq__(self, value):
                return value

        class FakeVariable:
            key = FakeKey()

            @staticmethod
            def set(name, value, session):
                self.assertIn(name, old_values)
                state["writes"] += 1
                session.candidate[name] = value

        class FakeDbSession:
            def __init__(self):
                self.candidate = dict(old_values)
                self.selected = None

            def query(self, model):
                return self

            def filter(self, expression):
                self.selected = expression
                return self

            def one(self):
                return self

            def get_val(self):
                return self.candidate[self.selected] if readback_matches else "unexpected-value"

        @contextmanager
        def create_session():
            session = FakeDbSession()
            try:
                yield session
            except Exception:
                state["rollbacks"] += 1
                raise
            else:
                state["stored"] = session.candidate

        class FakeResponse:
            def __init__(self, fail):
                self.status_code = 403 if fail else 200

            def json(self):
                return {
                    "code": 200,
                    "result": {"fieldList": [], "matrix": []},
                    "private": candidate,
                }

            def close(self):
                pass

        class FakeClient:
            trust_env = True

            def __init__(self):
                self.cookies = SimpleNamespace(clear=lambda: None)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def post(self, url, **kwargs):
                state["requests"].append((url, kwargs, self.trust_env))
                # Simulate third-party output; remote logging must discard it.
                print(candidate)
                print("private-subject", file=sys.stderr)
                return FakeResponse(fail_probe == len(state["requests"]))

        variable_module = ModuleType("airflow.models.variable")
        variable_module.Variable = FakeVariable
        session_module = ModuleType("airflow.utils.session")
        session_module.create_session = create_session
        watcher_module = ModuleType("wechat_airflow.venues.szw_watcher")
        watcher_module.SZW_HOST = "wlhmobile.crland.com.cn"
        watcher_module.SZW_APP_ID = "fake-app"
        watcher_module.SZW_MATRIX_API_URL = (
            "https://wlhmobile.crland.com.cn/business/client/field/area/matrix"
        )
        watcher_module.create_crland_http_session = FakeClient
        watcher_module.CRLAND_VENUES = {
            "szw": SimpleNamespace(
                booking_areas=(
                    SimpleNamespace(project_uuid="szw", field_area_uuid="outdoor"),
                    SimpleNamespace(project_uuid="szw", field_area_uuid="covered"),
                )
            ),
            "gba": SimpleNamespace(
                booking_areas=(SimpleNamespace(project_uuid="gba", field_area_uuid="gba"),)
            ),
        }
        modules = {
            "airflow.models.variable": variable_module,
            "airflow.utils.session": session_module,
            "wechat_airflow.venues.szw_watcher": watcher_module,
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        previous_logging = logging.root.manager.disable
        try:
            with (
                patch.dict(sys.modules, modules),
                patch.object(sys, "stdin", io.StringIO(candidate)),
                patch("time.sleep"),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as exit_result,
            ):
                exec(compile(sync_szw.REMOTE_PYTHON, "<rotation-test>", "exec"), {})
        finally:
            logging.disable(previous_logging)
        self.assertNotIn(candidate, stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("private-subject", stdout.getvalue() + stderr.getvalue())
        return state, json.loads(stdout.getvalue()), exit_result.exception.code

    def test_all_nine_read_only_probes_precede_atomic_pool_and_legacy_update(self):
        state, result, exit_code = self.run_remote()
        self.assertEqual(exit_code, 0)
        self.assertEqual(result, sync_szw.SUCCESS_RESULT)
        self.assertEqual(state["writes"], 2)
        self.assertEqual(state["rollbacks"], 0)
        self.assertEqual(len(state["requests"]), 9)
        for url, kwargs, trust_env in state["requests"]:
            self.assertEqual(
                url, "https://wlhmobile.crland.com.cn/business/client/field/area/matrix"
            )
            self.assertFalse(kwargs["allow_redirects"])
            self.assertFalse(trust_env)
            self.assertEqual(kwargs["timeout"], (5, 15))
        self.assertEqual(
            [request[1]["json"]["fieldAreaUuid"] for request in state["requests"]],
            ["outdoor", "covered", "gba"] * 3,
        )
        pool = json.loads(state["stored"][sync_szw.VARIABLE_NAME])
        self.assertEqual(len(pool), 3)
        self.assertEqual(state["stored"][sync_szw.LEGACY_VARIABLE_NAME], pool[0])

    def test_rejected_area_preserves_existing_credential(self):
        for failed_area in range(1, 10):
            with self.subTest(area=failed_area):
                state, result, exit_code = self.run_remote(fail_probe=failed_area)
                self.assertEqual(exit_code, 1)
                self.assertFalse(result["ok"])
                self.assertEqual(
                    state["stored"][sync_szw.LEGACY_VARIABLE_NAME], "previous-protected-value"
                )
                self.assertEqual(state["stored"][sync_szw.VARIABLE_NAME], "previous-protected-pool")
                self.assertEqual(state["writes"], 0)
                self.assertEqual(len(state["requests"]), failed_area)

    def test_readback_mismatch_rolls_back_replacement(self):
        state, result, exit_code = self.run_remote(readback_matches=False)
        self.assertEqual(exit_code, 1)
        self.assertEqual(result["error"], "variable_write_failed")
        self.assertEqual(state["stored"][sync_szw.LEGACY_VARIABLE_NAME], "previous-protected-value")
        self.assertEqual(state["stored"][sync_szw.VARIABLE_NAME], "previous-protected-pool")
        self.assertEqual(state["rollbacks"], 1)


class ProtectedRotationWorkflowTest(unittest.TestCase):
    def test_rotation_keeps_production_secret_and_exact_ci_gates(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")
        )
        operations = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"][
            "operation"
        ]["options"]
        self.assertIn("szw_authorization_sync", operations)
        job = workflow["jobs"]["operate"]
        self.assertEqual(job["environment"], "production")
        gate = next(
            step for step in job["steps"] if "Require verified exact commit" in step.get("name", "")
        )
        self.assertIn("szw_authorization_sync", gate["if"])
        self.assertIn("--required-check verify", gate["run"])
        self.assertIn("github_release_gate.py", gate["run"])
        execute = next(
            step for step in job["steps"] if step.get("name") == "Execute protected operation"
        )
        self.assertIn("secrets.SZW_API_AUTHORIZATIONS", execute["env"][sync_szw.VARIABLE_NAME])
        self.assertNotIn("inputs.SZW_API_AUTHORIZATIONS", json.dumps(workflow))
        runtime = yaml.safe_load((ROOT / "config/runtime-target.yaml").read_text(encoding="utf-8"))
        self.assertIn(
            "szw_authorization_sync", runtime["production_operations"]["airflow_operations"]
        )
        self.assertIn(
            sync_szw.VARIABLE_NAME, runtime["production_operations"]["github_environment_secrets"]
        )


if __name__ == "__main__":
    unittest.main()
