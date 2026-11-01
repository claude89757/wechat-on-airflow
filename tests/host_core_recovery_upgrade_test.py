"""Partial-release recovery keeps the original lifecycle gates and DB fence."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.engine import make_url

from wechat_airflow.host_core import database
from wechat_airflow.host_core.migration import EXPORT_TABLES

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "host_recovery", ROOT / "scripts/host_core_production.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
OLD = "b" * 40
NEW = "a" * 40
STAMP = datetime(2026, 11, 1, 2, 55, tzinfo=UTC)


def proof():
    return {
        "reconciliation": {
            "providerIdentityPreserved": True,
            **{
                name: {"sourceCount": 0, "matchedCount": 0, "keysSha256": "a" * 64}
                for name in EXPORT_TABLES
            },
        }
    }


def options(operation="snapshot"):
    return {
        "operation": operation,
        "runtimeCommit": OLD,
        "targetCommit": NEW,
        "updatedAt": STAMP.isoformat(),
    }


def state():
    return {
        "deployment_commit": OLD,
        "delivery_enabled": True,
        "wechat_enabled": False,
        "updated_at": STAMP,
        "activated_at": STAMP - timedelta(days=30),
        "phase": "active",
        "acceptance_started_at": STAMP - timedelta(days=1),
    }


class Result:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value

    def one(self):
        return self.value

    def scalar_one(self):
        return self.value


class Engine:
    def __init__(self):
        self.state = state()
        self.schema = True
        self.migration = proof()
        self.heartbeat = {
            "deployment_commit": OLD,
            "healthy": True,
            "updated_at": datetime.now(UTC),
            "details": {"mode": "active", "owner": True},
        }
        self.statements = []

    @contextmanager
    def begin(self):
        before = copy.deepcopy(self.state)
        try:
            yield self
        except Exception:
            self.state = before
            raise

    def execute(self, statement, values=None):
        sql = str(statement)
        self.statements.append(sql)
        if "to_regclass" in sql:
            return Result("zacks.schema_versions")
        if "SELECT EXISTS" in sql:
            return Result(self.schema)
        if "SELECT deployment_commit, delivery_enabled" in sql:
            return Result(copy.deepcopy(self.state))
        if "FROM zacks.migration_state" in sql:
            return Result({"imported_at": STAMP, "details": self.migration})
        if "FROM zacks.runtime_heartbeats" in sql:
            return Result(self.heartbeat)
        if sql.startswith("UPDATE"):
            assert values is not None
            assert self.state["deployment_commit"] == values["expected"]
            assert self.state["updated_at"] == values["stamp"]
            self.state.update(
                deployment_commit=values["target"],
                delivery_enabled=False,
                wechat_enabled=False,
                phase="prepared",
                updated_at=STAMP + timedelta(seconds=1),
                acceptance_started_at=None,
            )
            return Result(self.state["updated_at"])
        return Result(None)


@pytest.fixture
def app_probe(monkeypatch):
    namespace = {}
    # Exercise the exact program shipped to the existing API container.
    exec(MODULE.RECOVERY_PROBE.split("\ntry:\n    print(json.dumps(probe", 1)[0], namespace)
    monkeypatch.setenv("DEPLOYMENT_COMMIT", OLD)
    namespace["load_tencent_email_settings"] = lambda: None
    return namespace


def test_snapshot_is_read_only_and_fence_preserves_prior_activation(app_probe):
    engine = Engine()
    app_probe["get_engine"] = lambda: engine
    before = copy.deepcopy(engine.state)
    snapshot = app_probe["probe"](options())
    assert snapshot["heartbeat"]["owner"] is True
    assert engine.state == before
    assert "SET TRANSACTION READ ONLY" in engine.statements
    assert not any(
        sql.startswith(("UPDATE", "CREATE", "ALTER", "DELETE")) for sql in engine.statements
    )
    engine.statements.clear()
    result = app_probe["probe"](options("fence"))
    assert result["fencedAt"]
    assert engine.state["deployment_commit"] == NEW
    assert engine.state["delivery_enabled"] is False
    assert engine.state["wechat_enabled"] is False
    assert engine.state["activated_at"] == before["activated_at"]
    assert engine.state["acceptance_started_at"] is None
    assert engine.statements.index("SELECT pg_advisory_xact_lock(:key)") < next(
        i for i, sql in enumerate(engine.statements) if sql.startswith("UPDATE")
    )
    assert len([sql for sql in engine.statements if sql.startswith("UPDATE")]) == 1
    with pytest.raises(ValueError, match="control_identity_changed"):
        app_probe["probe"](options("fence"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("deployment_commit", "c" * 40),
        ("updated_at", STAMP + timedelta(seconds=1)),
        ("delivery_enabled", False),
        ("wechat_enabled", True),
        ("phase", "paused"),
        ("activated_at", None),
    ],
)
def test_control_changes_cannot_be_fenced(app_probe, field, value):
    engine = Engine()
    engine.state[field] = value
    original = copy.deepcopy(engine.state)
    app_probe["get_engine"] = lambda: engine
    with pytest.raises(ValueError):
        app_probe["probe"](options("fence"))
    assert engine.state == original
    assert not any(sql.startswith("UPDATE") for sql in engine.statements)


@pytest.mark.parametrize("missing", ["schema", "migration", "heartbeat", "owner"])
def test_read_only_preflight_requires_verified_migration_schema_and_active_owner(
    app_probe, missing
):
    engine = Engine()
    if missing == "schema":
        engine.schema = False
    elif missing == "migration":
        engine.migration = {}
    elif missing == "heartbeat":
        engine.heartbeat["updated_at"] = datetime.now(UTC) - timedelta(minutes=3)
    else:
        engine.heartbeat["details"]["owner"] = False
    app_probe["get_engine"] = lambda: engine
    with pytest.raises(ValueError):
        app_probe["probe"](options())
    assert not any(sql.startswith("UPDATE") for sql in engine.statements)


def runtime_images(wechat_status="exited", wechat_image="old-image", wechat_commit="c" * 40):
    return {
        "zacks-api": {"commit": OLD, "image": "live", "status": "running"},
        "zacks-notification-worker": {"commit": OLD, "image": "live", "status": "running"},
        "zacks-wechat-worker": {
            "commit": wechat_commit,
            "image": wechat_image,
            "status": wechat_status,
        },
    }


def test_stopped_wechat_may_keep_an_older_image():
    MODULE._require_recovery_runtime_images(runtime_images(), OLD)


def test_running_wechat_must_match_the_live_api_image():
    with pytest.raises(RuntimeError, match="images differ"):
        MODULE._require_recovery_runtime_images(runtime_images(wechat_status="running"), OLD)


def test_email_worker_must_match_the_live_api_image():
    current = runtime_images()
    current["zacks-notification-worker"]["image"] = "other"
    with pytest.raises(RuntimeError, match="images differ"):
        MODULE._require_recovery_runtime_images(current, OLD)


def test_recovery_failure_publishes_a_fixed_guard_and_hides_transport_text():
    assert (
        MODULE._public_recovery_reason(RuntimeError("active_mail_heartbeat_missing"))
        == "active_mail_heartbeat_missing"
    )
    assert (
        MODULE._public_recovery_reason(
            RuntimeError("recovery Host Core images differ from the expected runtime")
        )
        == "recovery Host Core images differ from the expected runtime"
    )
    assert MODULE._public_recovery_reason(RuntimeError("password=secret host=db.internal")) is None


def test_probe_failure_keeps_only_the_bounded_reason(monkeypatch):
    def fake_run(_command, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=(
                '{"ok": false, "errorClass": "ValueError", '
                '"reason": "active_mail_heartbeat_missing"}\n'
            ),
        )

    monkeypatch.setattr(MODULE, "run", fake_run)
    with pytest.raises(RuntimeError, match="^active_mail_heartbeat_missing$"):
        MODULE._recovery_probe(
            {"runtimeCommit": OLD, "updatedAt": STAMP.isoformat()},
            {"zacks-api": {"id": "abc"}},
        )


def test_probe_failure_drops_an_unbounded_reason(monkeypatch):
    def fake_run(_command, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout='{"ok": false, "errorClass": "OperationalError", "reason": "password=secret"}\n',
        )

    monkeypatch.setattr(MODULE, "run", fake_run)
    with pytest.raises(RuntimeError, match="recovery database identity") as caught:
        MODULE._recovery_probe(
            {"runtimeCommit": OLD, "updatedAt": STAMP.isoformat()},
            {"zacks-api": {"id": "abc"}},
        )
    assert "secret" not in str(caught.value)


def snapshot():
    return {
        "containers": {"zacks-api": {"id": "fixed", "image": "image", "commit": OLD}},
        "schemaRevision": "existing-revision",
        "state": {
            "activatedAt": STAMP.isoformat(),
            "updatedAt": STAMP.isoformat(),
            "deliveryEnabled": True,
            "wechatEnabled": False,
        },
        "heartbeat": {"updatedAt": STAMP.isoformat()},
    }


@pytest.fixture
def baseline(tmp_path, monkeypatch):
    directory = tmp_path / ".local" / "host-core-recovery"
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "RECOVERY_DIRECTORY", directory)
    recovery = MODULE.recovery_arguments(
        OLD, STAMP.isoformat(), "true", "false", str(directory / (NEW + "-123-1.json"))
    )
    with patch.object(MODULE, "recovery_snapshot", return_value=snapshot()):
        MODULE.capture_recovery_baseline(NEW, recovery)
    return recovery


def test_capture_never_overwrites_an_uncertain_prior_baseline(baseline):
    with (
        patch.object(MODULE, "recovery_snapshot", return_value=snapshot()),
        pytest.raises(FileExistsError),
    ):
        MODULE.capture_recovery_baseline(NEW, baseline)
    assert Path(baseline["baselineFile"]).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("changed", ["containers", "state", "schemaRevision"])
def test_source_prepare_refuses_changed_baseline_without_checkout(baseline, changed):
    current = snapshot()
    current[changed] = "changed"
    with (
        patch.object(MODULE, "recovery_snapshot", return_value=current),
        patch.object(MODULE, "run") as execute,
        pytest.raises(RuntimeError, match="baseline changed"),
    ):
        MODULE.prepare_recovery_source(NEW, baseline)
    execute.assert_not_called()


def test_source_restore_proves_identity_without_requiring_external_health(baseline):
    with (
        patch.object(MODULE, "recovery_snapshot", return_value=snapshot()) as observe,
        patch.object(MODULE, "run", return_value=SimpleNamespace(stdout=NEW + "\n")) as execute,
        patch.object(MODULE, "assert_target"),
    ):
        result = MODULE.restore_recovery_source(NEW, baseline)
    assert result["sourceRestored"]
    observe.assert_called_once_with(baseline, NEW, require_health=False)
    assert execute.call_args_list[-1].args[0] == ["git", "checkout", "--quiet", "--detach", OLD]


def test_source_restore_refuses_fenced_or_newer_control(baseline):
    current = snapshot()
    current["state"]["updatedAt"] = (STAMP + timedelta(seconds=1)).isoformat()
    with (
        patch.object(MODULE, "recovery_snapshot", return_value=current),
        patch.object(MODULE, "run", return_value=SimpleNamespace(stdout=NEW)) as execute,
        pytest.raises(RuntimeError, match="baseline changed"),
    ):
        MODULE.restore_recovery_source(NEW, baseline)
    assert execute.call_count == 1


@pytest.mark.parametrize("failure", ["build", "schema", "cas", None])
def test_recovery_prepares_before_fence_and_marks_only_committed_mutation(
    tmp_path, monkeypatch, failure, capsys
):
    monkeypatch.setattr(MODULE, "ROOT", tmp_path)
    monkeypatch.setenv("AIRFLOW_SECRET_DIR", str(tmp_path))
    (tmp_path / "zacks_edge_token").write_text("test-only-preserved-token")
    backups = tmp_path / ".local" / "host-core-backups"
    backups.mkdir(parents=True)
    backup = backups / ("zacks-" + NEW + ".dump")
    backup.write_text("test-only-backup")
    backup.chmod(0o600)
    calls = []

    def compose(*args, **kwargs):
        calls.append(args[0])
        if args[0] == failure:
            raise RuntimeError("test-only failure")

    def schema(*args):
        calls.append("schema")
        if failure == "schema":
            raise RuntimeError("test-only failure")

    def fence(*args, **kwargs):
        calls.append("fence")
        if failure == "cas":
            raise RuntimeError("control changed")

    with (
        patch.object(MODULE, "recovery_preflight", return_value=snapshot()),
        patch.object(MODULE, "preflight", return_value={}),
        patch.object(MODULE, "compose", side_effect=compose),
        patch.object(MODULE, "recovery_candidate_schema", side_effect=schema),
        patch.object(MODULE, "variable_get", return_value="test-only-preserved-token"),
        patch.object(MODULE, "verify_existing_configuration"),
        patch.object(MODULE, "_recovery_probe", side_effect=fence),
        patch.object(
            MODULE,
            "one_shot",
            side_effect=AssertionError("must not run schema/application writes before the fence"),
        ),
        patch.object(MODULE, "_wait_for_local_health"),
    ):
        if failure:
            with pytest.raises(RuntimeError):
                MODULE.prepare_runtime(NEW, recovery={"runtimeCommit": OLD})
        else:
            MODULE.prepare_runtime(NEW, recovery={"runtimeCommit": OLD})
    output = capsys.readouterr().out
    assert ("host_runtime_mutation_started" in output) is (failure is None)
    if failure:
        assert "stop" not in calls and "up" not in calls
    else:
        assert calls == ["build", "schema", "fence", "stop", "up"]


def test_workflow_captures_before_checkout_and_preserves_routine_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    steps = workflow["jobs"]["operate"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Capture recovery baseline before changing source") < names.index(
        "Prepare exact remote commit"
    )
    for step in steps:
        if "run" in step:
            result = subprocess.run(
                ["bash", "-n"], input=step["run"], text=True, capture_output=True, check=False
            )
            assert result.returncode == 0, result.stderr
    ast.parse((ROOT / "scripts/host_core_production.py").read_text(), feature_version=(3, 6))
    shell = (ROOT / "scripts/host_core_release.sh").read_text()
    assert shell.index("remote recovery-preflight") < shell.index(
        'remote prepare-runtime "${routine_args[@]}"'
    )
    assert "checkpoint-only" in shell


@pytest.mark.parametrize("failure", ["preflight", "prepare_guard", "after_fence", "checkpoint"])
def test_real_shell_recovery_failure_never_enters_first_migration(tmp_path, failure):
    source = (ROOT / "scripts/host_core_release.sh").read_text()
    control = source[source.index("changed=false\n") :]
    control = control.replace("/tmp/host-core-", str(tmp_path / "host-core-"))
    calls = tmp_path / "calls"
    setup = r"""set -Eeuo pipefail
OPERATION=recovery-upgrade
remote() {
  printf '%s\n' "$*" >> "$CALLS"
  if [[ "$1" == recovery-preflight && "$FAILURE" == preflight ]]; then return 7; fi
  if [[ "$1" == prepare-runtime ]]; then
    if [[ "$FAILURE" == after_fence || "$FAILURE" == checkpoint ]]; then
      echo '{"event": "host_runtime_mutation_started"}'
    fi
    if [[ "$FAILURE" != checkpoint ]]; then return 8; fi
  fi
}
checkpoint() { echo '{"migrationComplete":false}'; }
deploy_edge() { printf 'unexpected-edge\n' >> "$CALLS"; }
"""
    result = subprocess.run(
        ["bash", "-c", setup + control],
        env={
            **os.environ,
            "CALLS": str(calls),
            "FAILURE": failure,
            "RECOVERY_RUNTIME_COMMIT": OLD,
            "RECOVERY_CONTROL_UPDATED_AT": STAMP.isoformat(),
            "RECOVERY_DELIVERY_ENABLED": "true",
            "RECOVERY_WECHAT_ENABLED": "false",
            "RECOVERY_BASELINE_FILE": "test-only-evidence",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    operations = calls.read_text().splitlines()
    assert ("pause-host-delivery" in operations) is (failure in {"after_fence", "checkpoint"})
    assert not any(
        "migrate" in item
        or "sync-secrets" in item
        or "prepare-routing" in item
        or "unexpected-edge" in item
        for item in operations
    )


def test_real_postgres_recovery_cas_and_snapshot_never_applies_schema(app_probe, monkeypatch):
    url = os.environ.get("ZACKS_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("isolated PostgreSQL test URL not supplied")
    parsed = make_url(url)
    if parsed.database != "zacks_test" or parsed.host not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("Refusing destructive recovery fixture outside isolated zacks_test")
    monkeypatch.setenv("ZACKS_DATABASE_URL", url)
    database.reset_engine_for_test()
    engine = database.get_engine()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == "zacks_test"
        connection.execute(text("DROP SCHEMA IF EXISTS zacks CASCADE"))
    database.ensure_schema(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE zacks.runtime_control SET deployment_commit=:commit, delivery_enabled=true, wechat_enabled=false, activated_at=:stamp, updated_at=:stamp, phase='active'"
            ),
            {"commit": OLD, "stamp": STAMP},
        )
        connection.execute(
            text(
                "INSERT INTO zacks.migration_state(source,source_revision,imported_at,details) VALUES('cloudflare-d1','test',:stamp,CAST(:details AS jsonb))"
            ),
            {"stamp": STAMP, "details": json.dumps(proof())},
        )
        connection.execute(
            text(
                "INSERT INTO zacks.runtime_heartbeats(component,deployment_commit,healthy,updated_at,details) VALUES('zacks-notification-worker',:commit,true,now(),CAST(:details AS jsonb))"
            ),
            {"commit": OLD, "details": json.dumps({"owner": True, "mode": "active"})},
        )
    app_probe["get_engine"] = lambda: engine
    monkeypatch.setattr(
        database,
        "ensure_schema",
        lambda *args, **kwargs: pytest.fail("recovery attempted schema writes"),
    )
    try:
        assert app_probe["probe"](options())["state"]["deliveryEnabled"] is True
        app_probe["probe"](options("fence"))
        with pytest.raises(ValueError):
            app_probe["probe"](options("fence"))
        with engine.connect() as connection:
            value = connection.execute(text("SELECT * FROM zacks.runtime_control")).mappings().one()
            assert value["deployment_commit"] == NEW
            assert value["delivery_enabled"] is False and value["wechat_enabled"] is False
            assert value["activated_at"] == STAMP
            assert value["acceptance_started_at"] is None
    finally:
        database.reset_engine_for_test()
