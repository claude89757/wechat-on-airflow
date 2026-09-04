from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "host_core_production_restart_test",
    ROOT / "scripts" / "host_core_production.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_local_ready_wait_retries_transient_restart_errors() -> None:
    ready = {"ok": True, "databaseReady": True}
    with (
        patch.object(
            MODULE,
            "local_ready",
            side_effect=[RuntimeError("connection reset"), ready],
        ) as local_ready,
        patch.object(MODULE.time, "monotonic", side_effect=[0, 1, 2]),
        patch.object(MODULE.time, "sleep") as sleep,
    ):
        assert MODULE._wait_for_local_ready(timeout_seconds=10) == ready

    assert local_ready.call_count == 2
    sleep.assert_called_once_with(3)


def test_prepare_cutover_waits_after_restarting_api() -> None:
    target = "a" * 40
    health = {
        "ok": True,
        "deliveryOwner": "cloudflare",
        "observationMode": "host",
    }
    ready = {"ok": True, "databaseReady": True}
    with (
        patch.object(MODULE, "assert_target"),
        patch.object(MODULE, "check_ses_credentials"),
        patch.object(MODULE, "variable_set"),
        patch.object(MODULE, "compose") as compose,
        patch.object(MODULE, "_wait_for_local_health", return_value=health) as wait_health,
        patch.object(MODULE, "_wait_for_local_ready", return_value=ready) as wait_ready,
        patch.object(MODULE, "running_services", return_value=set()),
        patch.object(
            MODULE, "local_health", Mock(side_effect=AssertionError("immediate health call"))
        ),
        patch.object(
            MODULE, "local_ready", Mock(side_effect=AssertionError("immediate ready call"))
        ),
    ):
        result = MODULE.prepare_cutover(target)

    compose.assert_any_call("restart", "zacks-api")
    wait_health.assert_called_once_with(target)
    wait_ready.assert_called_once_with()
    assert result["notificationWorker"] == "stopped"
    assert result["localHealth"] == health
    assert result["localReady"] == ready
