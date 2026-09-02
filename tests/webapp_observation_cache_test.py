from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from wechat_airflow.notifications.observation_cache import (
    OBSERVATION_CACHE_ENABLED_ENV,
    OBSERVATION_CACHE_PATH_ENV,
    OBSERVATION_FAILURE_RETRY_SECONDS_ENV,
    OBSERVATION_HEARTBEAT_SECONDS_ENV,
    cached_gate_for_venue,
    decide_observation_delivery,
    observation_identity,
    record_observation_result,
)


class WebappObservationCacheTest(TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_path = Path(self.temporary.name) / "observations.json"
        self.environment = patch.dict(
            "os.environ",
            {
                OBSERVATION_CACHE_ENABLED_ENV: "true",
                OBSERVATION_CACHE_PATH_ENV: str(self.state_path),
                OBSERVATION_HEARTBEAT_SECONDS_ENV: "480",
                OBSERVATION_FAILURE_RETRY_SECONDS_ENV: "120",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.payload = {
            "venue_id": "szw",
            "venue_name": "深圳湾",
            "observation_scope": "check_and_notify_day_0",
            "healthy": True,
            "checked_at": "2026-09-02T09:00:00.000Z",
            "error": None,
            "slots": [
                {
                    "date": "2026-09-03",
                    "court_name": "2号场",
                    "start_time": "19:00",
                    "end_time": "20:00",
                },
                {
                    "date": "2026-09-03",
                    "court_name": "1号场",
                    "start_time": "18:00",
                    "end_time": "19:00",
                },
            ],
        }
        self.gate = {
            "allowed": True,
            "evaluated_at": "2026-09-02T09:00:00+00:00",
            "valid_until": "2026-09-02T09:10:00+00:00",
            "revision": 123,
        }

    def test_fingerprint_ignores_checked_at_and_slot_order(self) -> None:
        first = observation_identity(self.payload)
        second = observation_identity(
            {
                **self.payload,
                "checked_at": "2026-09-02T09:00:15.000Z",
                "slots": list(reversed(self.payload["slots"])),
            }
        )
        self.assertEqual(first, second)

    def test_changed_payload_always_forwards(self) -> None:
        first = decide_observation_delivery(self.payload, now=1_000)
        record_observation_result(first, success=True, gate=self.gate, now=1_000)
        changed = decide_observation_delivery(
            {**self.payload, "slots": self.payload["slots"][:1]},
            now=1_015,
        )
        self.assertEqual(changed.action, "forward")

    def test_success_suppresses_unchanged_polls_until_sparse_heartbeat(self) -> None:
        first = decide_observation_delivery(self.payload, now=1_000)
        self.assertEqual(first.action, "forward")
        record_observation_result(first, success=True, gate=self.gate, now=1_000)

        recent = decide_observation_delivery(self.payload, now=1_015)
        heartbeat = decide_observation_delivery(self.payload, now=1_480)
        self.assertEqual(recent.action, "skip_success")
        self.assertEqual(recent.gate, self.gate)
        self.assertEqual(heartbeat.action, "forward")

    def test_parallel_scopes_share_one_venue_heartbeat_budget(self) -> None:
        day_zero = decide_observation_delivery(self.payload, now=1_000)
        record_observation_result(day_zero, success=True, gate=self.gate, now=1_000)

        day_one_payload = {
            **self.payload,
            "observation_scope": "check_and_notify_day_1",
        }
        day_one = decide_observation_delivery(day_one_payload, now=1_001)
        self.assertEqual(day_one.action, "forward")
        record_observation_result(day_one, success=True, gate=self.gate, now=1_001)

        due = decide_observation_delivery(self.payload, now=1_481)
        self.assertEqual(due.action, "forward")
        record_observation_result(due, success=True, gate=self.gate, now=1_481)

        coalesced = decide_observation_delivery(day_one_payload, now=1_482)
        self.assertEqual(coalesced.action, "skip_success")

    def test_failure_retries_are_bounded_but_changes_bypass_the_backoff(self) -> None:
        first = decide_observation_delivery(self.payload, now=2_000)
        record_observation_result(first, success=False, gate=None, now=2_000)

        recent = decide_observation_delivery(self.payload, now=2_030)
        changed = decide_observation_delivery(
            {**self.payload, "healthy": False, "error": "upstream unavailable", "slots": []},
            now=2_030,
        )
        retry = decide_observation_delivery(self.payload, now=2_120)
        self.assertEqual(recent.action, "skip_retry")
        self.assertEqual(changed.action, "forward")
        self.assertEqual(retry.action, "skip_retry")

    def test_failed_change_is_not_hidden_by_an_older_healthy_heartbeat(self) -> None:
        baseline = decide_observation_delivery(self.payload, now=3_000)
        record_observation_result(baseline, success=True, gate=self.gate, now=3_000)
        changed_payload = {**self.payload, "slots": self.payload["slots"][:1]}

        changed = decide_observation_delivery(changed_payload, now=3_010)
        self.assertEqual(changed.action, "forward")
        record_observation_result(changed, success=False, gate=self.gate, now=3_010)

        recent = decide_observation_delivery(changed_payload, now=3_060)
        retry = decide_observation_delivery(changed_payload, now=3_130)
        self.assertEqual(recent.action, "skip_retry")
        self.assertEqual(retry.action, "forward")

    def test_gate_survives_process_independent_file_roundtrip(self) -> None:
        decision = decide_observation_delivery(self.payload, now=4_000)
        record_observation_result(decision, success=True, gate=self.gate, now=4_000)

        self.assertEqual(cached_gate_for_venue("szw"), self.gate)
        stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], 2)
        self.assertEqual(len(stored["entries"]), 1)
        self.assertEqual(len(stored["venues"]), 1)
        self.assertEqual(self.state_path.stat().st_mode & 0o777, 0o600)
