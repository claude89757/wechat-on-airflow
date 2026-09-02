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
                OBSERVATION_HEARTBEAT_SECONDS_ENV: "300",
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

    def test_success_suppresses_unchanged_polls_until_heartbeat(self) -> None:
        first = decide_observation_delivery(self.payload, now=1_000)
        self.assertEqual(first.action, "forward")
        record_observation_result(first, success=True, gate=self.gate, now=1_000)

        recent = decide_observation_delivery(self.payload, now=1_015)
        heartbeat = decide_observation_delivery(self.payload, now=1_300)
        self.assertEqual(recent.action, "skip_success")
        self.assertEqual(recent.gate, self.gate)
        self.assertEqual(heartbeat.action, "forward")

    def test_failure_retries_are_bounded_but_changes_bypass_the_backoff(self) -> None:
        first = decide_observation_delivery(self.payload, now=2_000)
        record_observation_result(first, success=False, gate=None, now=2_000)

        recent = decide_observation_delivery(self.payload, now=2_030)
        retry = decide_observation_delivery(self.payload, now=2_120)
        changed = decide_observation_delivery(
            {**self.payload, "healthy": False, "error": "upstream unavailable", "slots": []},
            now=2_030,
        )
        self.assertEqual(recent.action, "skip_retry")
        self.assertEqual(retry.action, "forward")
        self.assertEqual(changed.action, "forward")

    def test_gate_survives_process_independent_file_roundtrip(self) -> None:
        decision = decide_observation_delivery(self.payload, now=3_000)
        record_observation_result(decision, success=True, gate=self.gate, now=3_000)

        self.assertEqual(cached_gate_for_venue("szw"), self.gate)
        stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], 1)
        self.assertEqual(len(stored["entries"]), 1)
        self.assertEqual(self.state_path.stat().st_mode & 0o777, 0o600)
