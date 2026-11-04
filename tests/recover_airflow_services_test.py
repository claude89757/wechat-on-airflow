from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import production_health  # noqa: E402
import recover_airflow_services as recover  # noqa: E402


def inventory(**services):
    base = {
        "zacks-api": [{"id": "zacks", "status": "running"}],
        "postgresql": [{"id": "pg", "status": "running"}],
        "redis": [{"id": "redis", "status": "running"}],
    }
    base.update(services)
    return base


def test_stopped_api_server_is_started_without_creating_a_second_copy():
    plan = recover.plan_actions(
        inventory(
            **{
                "airflow-api-server": [
                    {
                        "id": "old",
                        "status": "exited",
                        "finished_at": "2026-11-04T05:00:00Z",
                        "restart_count": 0,
                        "oom_killed": False,
                    },
                    {
                        "id": "newer",
                        "status": "exited",
                        "finished_at": "2026-11-04T05:13:00Z",
                        "restart_count": 0,
                        "oom_killed": False,
                    },
                ]
            }
        ),
        None,
    )

    api = [item for item in plan["actions"] if item["service"] == "airflow-api-server"]
    assert [item["action"] for item in api] == ["report", "start"]
    assert api[1]["id"] == "newer"
    assert "zacks-api" not in {item["service"] for item in plan["actions"]}


def test_crash_loop_and_missing_anchor_do_not_mutate():
    looping = recover.recovery_action(
        {
            "id": "api",
            "status": "restarting",
            "health": "",
            "restart_count": 9,
            "oom_killed": True,
        }
    )
    assert looping == "report"

    plan = recover.plan_actions(
        {
            "postgresql": [{"id": "pg", "status": "exited"}],
            "redis": [{"id": "redis", "status": "running"}],
            "zacks-api": [{"id": "zacks", "status": "running"}],
            "airflow-api-server": [
                {"id": "api", "status": "exited", "restart_count": 0, "oom_killed": False}
            ],
        },
        None,
    )
    assert plan["blocked_data_services"] == ["postgresql"]
    assert all(item["action"] == "report" for item in plan["actions"])


def test_healthy_origin_is_left_unchanged_and_closed_origin_restarts_once():
    running = {
        "id": "api",
        "status": "running",
        "health": "healthy",
        "restart_count": 12,
        "oom_killed": False,
    }
    assert recover.origin_blocked_action(recover.recovery_action(running), 200) == "keep"
    assert recover.origin_blocked_action(recover.recovery_action(running), None) == "restart"
    assert recover.redact_text("postgresql://airflow:secret@db/airflow") == "<redacted-url>"


def test_remote_program_only_starts_existing_application_containers():
    script = recover.remote_script()
    program = script.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]

    ast.parse(program)
    assert 'docker", "start"' in program or '["docker", "start"' in program
    assert "--no-deps" in program
    assert "--no-build" in program
    for forbidden in (
        "git checkout",
        "git reset",
        "git clean",
        "FLUSHDB",
        "compose down",
        "docker rm",
        "volume rm",
    ):
        assert forbidden not in script


def test_ssh_warning_does_not_hide_the_remote_failure():
    warning = "\n".join(
        [
            "WARNING: connection is not using a post-quantum key exchange algorithm.",
            'This session may be vulnerable to "store now, decrypt later" attacks.',
            "The server may need to be upgraded. See https://openssh.com/pq.html",
        ]
    )

    assert (
        production_health.ssh_failure_detail(warning, "airflow-api-server is not running\n")
        == "airflow-api-server is not running"
    )


def test_service_recover_is_a_protected_airflow_operation():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")
    )
    trigger = workflow.get("on", workflow.get(True))
    operations = trigger["workflow_dispatch"]["inputs"]["operation"]["options"]
    execute = next(
        step
        for step in workflow["jobs"]["operate"]["steps"]
        if step.get("name") == "Execute protected operation"
    )
    runtime = yaml.safe_load((ROOT / "config/runtime-target.yaml").read_text(encoding="utf-8"))
    contract = (ROOT / "scripts/check_active_components.py").read_text(encoding="utf-8")
    dispatcher = (ROOT / "scripts/github_production.py").read_text(encoding="utf-8")

    assert operations[1] == "service_recover"
    assert "scripts/recover_airflow_services.py" in execute["run"]
    assert "--operation-commit" in execute["run"]
    assert runtime["production_operations"]["airflow_operations"][1] == "service_recover"
    assert '"service_recover"' in contract
    assert '"service_recover"' in dispatcher
