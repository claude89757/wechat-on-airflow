"""Exercise protected preflight reports with fake host I/O, never a live Pi."""

from __future__ import annotations

import hashlib
import io
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from tests.pi_appium_mcp_test import DEPLOY, INSTALL

PRIVATE = "PRIVATE_TOKEN https://private.invalid Authorization=secret command --password=secret"


@pytest.fixture
def preflight(monkeypatch, tmp_path):
    state = {"fail": None, "health_round": 0, "calls": []}
    base, staging = tmp_path / "runtime", tmp_path / "staging"
    staging.mkdir()
    archive = b"test-only-node-archive"
    (staging / "node.tar.xz").write_bytes(archive)
    monkeypatch.setattr(INSTALL, "BASE", base)
    monkeypatch.setattr(INSTALL, "NODE_SHA", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(
        INSTALL.sys,
        "argv",
        ["install.py", "preflight", "--commit", "a" * 40, "--staging", str(staging)],
    )
    monkeypatch.setattr(INSTALL.os, "geteuid", lambda: 1 if state["fail"] == "validation" else 0)
    monkeypatch.setattr(INSTALL.pwd, "getpwnam", lambda _: object())
    monkeypatch.setattr(
        INSTALL.shutil,
        "disk_usage",
        lambda _: SimpleNamespace(free=1 if state["fail"] == "candidate_disk" else 3_000_000_000),
    )
    monkeypatch.setattr(
        INSTALL.shutil,
        "which",
        lambda _: None if state["fail"] == "cloudflared_missing" else "/usr/bin/cloudflared",
    )
    monkeypatch.setattr(
        INSTALL.urllib.request, "urlopen", lambda *a, **k: nullcontext(SimpleNamespace(status=200))
    )
    test_report = INSTALL.summarize_tests(b"<testsuites><testcase/></testsuites>", 0)

    def fail():
        raise RuntimeError(PRIVATE)

    def command(argv, **kwargs):
        state["calls"].append(argv)
        point = state["fail"]
        if argv[0] == "systemctl":
            if argv[-1] == "wechat-sender.service":
                state["health_round"] += 1
            if argv[-1] == "zacks-agent.service" and (
                (point == "existing_health" and state["health_round"] == 1)
                or (point == "post_preflight_health" and state["health_round"] == 2)
            ):
                fail()
        if argv[0] == "usermod" and point == "service_account":
            fail()
        if argv[0] == "runuser" and point == "cloudflared_service_user_failed":
            fail()
        if argv[-1] == "--help":
            if point == "cloudflared_help_failed":
                fail()
            return (
                ""
                if point == "cloudflared_flags_unsupported"
                else "--metrics --log-directory --token-file"
            )
        if argv[-1] == "process.arch":
            return "x64" if point == "node_runtime" else "arm"
        if argv[0].endswith("/npm"):
            assert kwargs["env"]["npm_config_offline"] == "true"
            assert "--ignore-scripts" in argv and "--omit=optional" in argv
            if point == "offline_dependencies":
                fail()
        return ""

    def unpack(source, destination, **kwargs):
        if (source.name == "source.tar.gz" and state["fail"] == "source_bundle") or (
            source.name == "cache.tar.gz" and state["fail"] == "dependency_cache"
        ):
            fail()
        destination.mkdir(parents=True, exist_ok=True)
        if source.name == "source.tar.gz":
            for name in (
                "server.mjs",
                "guard.mjs",
                "lock-holder.py",
                "smoke.mjs",
                "package.json",
                "package-lock.json",
                ".npmrc",
                "pi-appium-mcp.service",
                "test/guard.test.mjs",
                "test/transport.test.mjs",
            ):
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")

    def candidate_tests(*args):
        if state["fail"] == "candidate_tests":
            raise INSTALL.CandidateTestFailure({**test_report, "exitCode": 1, "failed": [1]})
        return test_report

    private_write = INSTALL.verify_private_write
    rmtree = INSTALL.shutil.rmtree

    def verify_private(candidate):
        if state["fail"] == "private_write":
            fail()
        private_write(candidate)

    def cleanup(path, *args, **kwargs):
        if state["fail"] == "candidate_cleanup":
            fail()
        return rmtree(path, *args, **kwargs)

    monkeypatch.setattr(INSTALL, "run", command)
    monkeypatch.setattr(INSTALL, "unpack", unpack)
    monkeypatch.setattr(INSTALL, "run_candidate_tests", candidate_tests)
    monkeypatch.setattr(INSTALL, "verify_private_write", verify_private)
    monkeypatch.setattr(INSTALL.shutil, "rmtree", cleanup)
    monkeypatch.setattr(
        INSTALL,
        "prune_incomplete_candidates",
        lambda: fail() if state["fail"] == "candidate_reclaim" else 0,
    )
    state.update(base=base, staging=staging, test_report=test_report)
    return state


@pytest.mark.parametrize(
    ("point", "stage", "code"),
    [
        ("validation", "validation", "invalid_operation"),
        ("existing_health", "existing_health", "agent_service_inactive"),
        ("node_archive", "node_archive", "node_archive_invalid"),
        ("candidate_reclaim", "candidate_reclaim", "candidate_reclaim_failed"),
        ("candidate_disk", "candidate_disk", "candidate_disk_insufficient"),
        ("service_account", "service_account", "service_account_unavailable"),
        ("cloudflared_missing", "connector_runtime", "cloudflared_missing"),
        ("cloudflared_help_failed", "connector_runtime", "cloudflared_help_failed"),
        ("cloudflared_flags_unsupported", "connector_runtime", "cloudflared_flags_unsupported"),
        ("cloudflared_service_user_failed", "connector_runtime", "cloudflared_service_user_failed"),
        ("node_runtime", "node_runtime", "node_runtime_invalid"),
        ("source_bundle", "source_bundle", "source_bundle_invalid"),
        ("private_write", "private_write", "private_write_failed"),
        ("dependency_cache", "dependency_cache", "dependency_cache_invalid"),
        ("offline_dependencies", "offline_dependencies", "offline_dependency_install_failed"),
        ("candidate_tests", "candidate_tests", "candidate_tests_failed"),
        ("candidate_cleanup", "candidate_cleanup", "candidate_cleanup_failed"),
        ("post_preflight_health", "post_preflight_health", "agent_service_inactive"),
    ],
)
def test_preflight_failures_are_located_without_skipping_checks_or_leaking_messages(
    preflight, point, stage, code
):
    preflight["fail"] = point
    if point == "node_archive":
        (preflight["staging"] / "node.tar.xz").write_bytes(b"tampered")
    with pytest.raises(Exception) as caught:
        INSTALL.main()
    report = INSTALL.failure_report(caught.value)
    assert report["ok"] is False and report["externalTestSends"] == 0
    assert report["failureDiagnostic"] == {"stage": stage, "errorCode": code}
    assert "PRIVATE" not in json.dumps(report)
    assert "private.invalid" not in json.dumps(report)
    if point == "candidate_tests":
        assert report["errorClass"] == "CandidateTestFailure"
        assert report["candidateTests"]["failed"] == [1]


def test_successful_preflight_result_and_no_activation_are_unchanged(preflight):
    report = INSTALL.main()
    assert report == {
        "ok": True,
        "candidateVerified": True,
        "applied": False,
        "externalTestSends": 0,
        "candidateTests": preflight["test_report"],
        "prunedIncompleteCandidates": 0,
    }
    assert preflight["health_round"] == 2
    assert not list(preflight["base"].glob("candidate-*"))
    assert not any("start" in call or "restart" in call for call in preflight["calls"])


def failed_remote(report):
    channel = SimpleNamespace(shutdown_write=lambda: None, recv_exit_status=lambda: 1)
    stdin = SimpleNamespace(write=lambda _: None, flush=lambda: None, channel=channel)
    stdout = io.BytesIO(json.dumps(report).encode())
    stdout.channel = channel
    return SimpleNamespace(
        exec_command=lambda *a, **k: (stdin, stdout, io.BytesIO(PRIVATE.encode()))
    )


def test_failure_context_crosses_remote_boundary_only_for_valid_fixed_pairs():
    assert INSTALL.FAILURE_DIAGNOSTICS == DEPLOY.FAILURE_DIAGNOSTICS
    valid = {"stage": "offline_dependencies", "errorCode": "offline_dependency_install_failed"}
    malformed = [
        None,
        [],
        {**valid, "stderr": PRIVATE},
        {**valid, "stage": PRIVATE},
        {**valid, "errorCode": PRIVATE},
        {**valid, "stage": []},
        {**valid, "errorCode": True},
        {**valid, "errorCode": "agent_service_inactive"},
    ]
    for diagnostic in [valid, *malformed]:
        report = {
            "ok": False,
            "errorClass": "RuntimeError",
            "failureDiagnostic": diagnostic,
            "stderr": PRIVATE,
        }
        with pytest.raises(DEPLOY.RemoteOperationError) as caught:
            DEPLOY.remote(failed_remote(report), "not-executed")
        assert caught.value.diagnostic == (valid if diagnostic == valid else None)
        assert PRIVATE not in json.dumps(caught.value.__dict__)
        assert str(caught.value) == "pi_operation_failed"
        assert INSTALL.safe_failure_diagnostic(diagnostic) == DEPLOY.safe_failure_diagnostic(
            diagnostic
        )
    # A mislabeled remote success with a nonzero exit still fails without trusting its detail.
    with pytest.raises(DEPLOY.RemoteOperationError) as caught:
        DEPLOY.remote(failed_remote({"ok": True, "failureDiagnostic": valid}), "not-executed")
    assert caught.value.diagnostic is None


def test_runner_prints_only_sanitized_remote_diagnostics(monkeypatch, capsys):
    valid = {"stage": "existing_health", "errorCode": "agent_service_inactive"}
    for key, value in {
        "TARGET_COMMIT": "a" * 40,
        "OPERATION": "preflight",
        "CLOUDFLARE_ACCOUNT_ID": PRIVATE,
        "PI_DEVICE_SSH_HOST": PRIVATE,
        "PI_DEVICE_SSH_PORT": "22",
        "PI_DEVICE_SSH_USER": PRIVATE,
        "PI_DEVICE_SSH_PASSWORD": PRIVATE,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("RUNTIME_COMMIT", raising=False)
    monkeypatch.setattr(DEPLOY, "cf", lambda *a, **k: {})
    client = SimpleNamespace(
        set_missing_host_key_policy=lambda _: None,
        connect=lambda *a, **k: None,
        open_sftp=lambda: nullcontext(SimpleNamespace(put=lambda *a: None)),
        close=lambda: None,
    )
    monkeypatch.setattr(DEPLOY.paramiko, "SSHClient", lambda: client)

    def remote(_client, command, *args, **kwargs):
        if " preflight " in command:
            DEPLOY.remote_before_test(
                failed_remote(
                    {
                        "ok": False,
                        "errorClass": "RuntimeError",
                        "failureDiagnostic": valid,
                        "message": PRIVATE,
                        "env": {"secret": PRIVATE},
                    }
                ),
                "not-executed",
            )
        return ""

    monkeypatch.setattr(DEPLOY, "remote_before_test", DEPLOY.remote, raising=False)
    monkeypatch.setattr(DEPLOY, "remote", remote)
    assert DEPLOY.main() == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["phase"] == "pi_preflight"
    assert report["remoteErrorClass"] == "RuntimeError"
    assert report["failureDiagnostic"] == valid
    assert report["externalTestSends"] == 0
    assert PRIVATE not in output and "private.invalid" not in output
