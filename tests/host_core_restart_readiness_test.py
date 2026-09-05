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


def test_prepare_routing_waits_for_both_health_and_readiness():
    target = "a" * 40
    with (
        patch.object(MODULE, "assert_target"),
        patch.object(MODULE, "variable_set"),
        patch.object(MODULE, "compose_exec"),
        patch.object(MODULE, "_wait_for_local_health") as health,
        patch.object(MODULE, "_wait_for_local_ready") as ready,
        patch.object(MODULE, "local_health", Mock(side_effect=AssertionError("one-shot probe"))),
    ):
        result = MODULE.prepare_routing(target)
    health.assert_called_once_with(target)
    ready.assert_called_once_with()
    assert result["ready"] is True
