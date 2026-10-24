from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/diagnose_airflow_deploy_preflight.py"


def probes():
    tree = ast.parse(SOURCE.read_text())
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "BUSINESS_BASELINE_PROBE"
            for target in node.targets
        )
    )
    probe = ast.literal_eval(assignment.value)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "remote_script"
    )
    namespace = {"BUSINESS_BASELINE_PROBE": probe}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "remote-shell", "exec"), namespace)
    return probe, namespace["remote_script"]()


def sanitizer():
    _, shell = probes()
    final = shell.split("python3 - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    tree = ast.parse(final)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "business_baseline"
    )
    namespace = {"json": json, "re": re, "datetime": datetime}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "baseline-sanitizer", "exec"),
        namespace,
    )
    return namespace["business_baseline"]


@pytest.mark.parametrize("state", ["retired_stale", "retired_absent", "query_failure"])
def test_fixed_probe_is_read_only_and_aggregate_only(state):
    commands = []
    probe, _ = probes()

    class Result:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

        def one(self):
            return self.row

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def begin(self):
            return self

        def execute(self, sql):
            commands.append(sql)
            if "FROM zacks.observation_state WHERE observation_key =" in sql:
                if state == "query_failure":
                    raise RuntimeError("PRIVATE DATABASE URL AND EMAIL")
                return Result(
                    None
                    if state == "retired_absent"
                    else {
                        "healthy": True,
                        "fresh": False,
                        "last_seen_at": datetime(2026, 10, 20, tzinfo=UTC),
                    }
                )
            if "FROM zacks.observation_state WHERE observation_key <>" in sql:
                return Result(
                    {
                        "total_count": 28,
                        "healthy_count": 28,
                        "fresh_count": 27,
                        "healthy_and_fresh_count": 27,
                    }
                )
            if "zacks.notification_outbox" in sql:
                return Result({"email_delivered": 12, "wechat_sent": 4})
            if "zacks.runtime_control" in sql:
                return Result(
                    {
                        "deployment_commit": "a" * 40,
                        "delivery_enabled": True,
                        "wechat_enabled": True,
                        "activated": True,
                        "observed_at": datetime(2026, 10, 24, tzinfo=UTC),
                    }
                )
            return Result(None)

    sqlalchemy = ModuleType("sqlalchemy")
    sqlalchemy.text = lambda value: value
    database = ModuleType("wechat_airflow.host_core.database")
    database.get_engine = lambda: type("Engine", (), {"connect": lambda self: Connection()})()
    output = io.StringIO()
    with (
        patch.dict(
            "sys.modules", {"sqlalchemy": sqlalchemy, "wechat_airflow.host_core.database": database}
        ),
        patch.dict("os.environ", {"DEPLOYMENT_COMMIT": "b" * 40}),
        contextlib.redirect_stdout(output),
    ):
        exec(compile(probe, "fixed-baseline-probe", "exec"), {})
    report = json.loads(output.getvalue())
    assert commands[:3] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '5s'",
        "SET LOCAL lock_timeout = '1s'",
    ]
    assert all(command.startswith("SELECT ") for command in commands[3:])
    assert "PRIVATE" not in output.getvalue()
    if state == "query_failure":
        assert report == {
            "ok": False,
            "read_only": True,
            "failure_category": "business_baseline_query_failed",
        }
        assert sanitizer()(output.getvalue())["ok"] is False
    else:
        assert report["ok"] is True
        assert report["retired_scope"]["present"] is (state == "retired_stale")
        assert report["retired_scope"]["fresh"] is (False if state == "retired_stale" else None)
        assert report["non_retired_stored_scopes"]["fresh_count"] == 27
        assert report["natural_delivery_last24h"] == {"email_delivered": 12, "wechat_sent": 4}
        assert report["runtime"]["container_commit"] == "b" * 40
        report["private"] = "PRIVATE VALUE"
        report["runtime"]["private"] = "PRIVATE VALUE"
        clean = sanitizer()(json.dumps(report))
        assert "PRIVATE" not in json.dumps(clean)
        assert clean["purpose"] == "baseline_only_not_release_acceptance"
        assert clean["observed_at"] == "2026-10-24T00:00:00+00:00"
        assert clean["retired_scope"]["last_seen_at"] == (
            "2026-10-20T00:00:00+00:00" if state == "retired_stale" else None
        )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "{}",
        '{"ok":true,"read_only":false}',
        '{"ok":false,"failure_category":"PRIVATE VALUE"}',
    ],
)
def test_missing_or_unexpected_probe_fails_closed_without_raw_text(raw):
    clean = sanitizer()(raw)
    assert clean == {
        "ok": False,
        "read_only": True,
        "failure_category": "business_baseline_probe_failed",
    }


def test_official_preflight_collects_baseline_without_mutation_or_runtime_initialization():
    probe, shell = probes()
    assert "compose exec -T zacks-api python - 2>/dev/null" in shell
    assert 'baseline = business_baseline(os.environ["DIAG_BUSINESS_BASELINE"])' in shell
    assert 'elif baseline["ok"] is not True:' in shell
    assert 'failed_stage = "business_baseline_probe"' in shell
    assert '"business_baseline": baseline' in shell
    assert "from wechat_airflow.host_core.database import get_engine" in probe
    assert "transaction()" not in probe
    assert "runtime_state(" not in probe
    assert "ensure_schema" not in probe
    assert "check_and_notify_day_3" in probe
    assert "count(DISTINCT message_id)" in probe
    assert "status = 'delivered' AND submitted_at >=" in probe
    assert "SELECT *" not in probe
    assert "git checkout" not in shell
    assert "systemctl restart" not in shell
    result = subprocess.run(
        ["bash", "-n"], input=shell, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_outer_timestamp_sanitizer_keeps_host_python36_compatibility():
    script = SOURCE.read_text()
    assert "datetime.fromisoformat(" not in script
    assert "datetime.strptime(normalized, timestamp_format)" in script
