from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "restart_if_unhealthy.py"

sys.path.insert(0, str(ROOT / "scripts"))

import restart_if_unhealthy as restart  # noqa: E402


def test_one_failure_waits_and_the_fifth_restarts():
    assert restart.failure_action(0, healthy=False) == (1, "wait")
    assert restart.failure_action(3, healthy=False) == (4, "wait")
    assert restart.failure_action(4, healthy=False) == (5, "restart")


def test_success_resets_the_failure_count():
    assert restart.failure_action(4, healthy=True) == (0, "ok")


def test_script_stops_only_the_requested_process(tmp_path: Path):
    target = subprocess.Popen(["sleep", "30"])
    try:
        first = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--name",
                "api-server",
                "--state-dir",
                str(tmp_path),
                "--pid",
                str(target.pid),
                "--limit",
                "2",
                "--",
                "false",
            ],
            check=False,
        )
        assert first.returncode == 1
        assert target.poll() is None
        assert (tmp_path / "airflow-unhealthy-api-server").read_text(encoding="utf-8") == "1\n"

        second = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--name",
                "api-server",
                "--state-dir",
                str(tmp_path),
                "--pid",
                str(target.pid),
                "--limit",
                "2",
                "--",
                "false",
            ],
            check=False,
        )
        assert second.returncode == 1
        assert target.wait(timeout=5) != 0
    finally:
        if target.poll() is None:
            target.kill()
            target.wait(timeout=5)


def test_compose_restarts_wedged_api_and_triggerer_processes():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "command: api-server --workers 2 --proxy-headers" in compose
    assert compose.count("restart_if_unhealthy.py") == 2
    assert "--name api-server -- curl --fail --max-time 8" in compose
    assert "--name triggerer -- airflow jobs check --job-type TriggererJob" in compose
