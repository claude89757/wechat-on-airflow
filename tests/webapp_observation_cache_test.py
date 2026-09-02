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
        self.empty_payload = {**self.payload, "slots": []}
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

    def test_in_flight_reservation_blocks_a_parallel_duplicate(self) -> None:
        first = decide_observation_delivery(self.empty_payload, now=1_000)
        parallel = decide_observation_delivery(self.empty_payload, now=1_001)

        self.assertEqual(first.action, "forward")
        self.assertEqual(parallel.action, "skip_retry")

    def test_changed_payload_always_forwards(self) -> None:
        first = decide_observation_delivery(self.empty_payload, now=1_000)
        record_observation_result(first, success=True, gate=self.gate, now=1_000)
        changed = decide_observation_delivery(self.payload, now=1_015)
        self.assertEqual(changed.action, "forward")

    def test_available_slots_recheck_subscriptions_on_every_natural_poll(self) -> None:
        first = decide_observation_delivery(self.payload, now=1_000)
        record_observation_result(first, success=True, gate=self.gate, now=1_000)

        next_poll = decide_observation_delivery(self.payload, now=1_015)
        self.assertEqual(next_poll.action, "forward")

    def test_available_slot_failure_uses_retry_backoff_after_prior_success(self) -> None:
        first = decide_observation_delivery(self.payload, now=1_000)
        record_observation_result(first, success=True, gate=self.gate, now=1_000)
        retrying = decide_observation_delivery(self.payload, now=1_015)
        record_observation_result(retrying, success=False, gate=self.gate, now=1_015)

        recent = decide_observation_delivery(self.payload, now=1_030)
        due = decide_observation_delivery(self.payload, now=1_135)
        self.assertEqual(recent.action, "skip_retry")
        self.assertEqual(due.action, "forward")

    def test_empty_success_never_emits_a_heartbeat(self) -> None:
        first = decide_observation_delivery(self.empty_payload, now=1_000)
        self.assertEqual(first.action, "forward")
        record_observation_result(first, success=True, gate=self.gate, now=1_000)

        recent = decide_observation_delivery(self.empty_payload, now=1_015)
        much_later = decide_observation_delivery(self.empty_payload, now=100_000)
        self.assertEqual(recent.action, "skip_success")
        self.assertEqual(recent.gate, self.gate)
        self.assertEqual(much_later.action, "skip_success")

    def test_parallel_empty_scopes_initialize_once_then_stay_local(self) -> None:
        day_zero = decide_observation_delivery(self.empty_payload, now=1_000)
        record_observation_result(day_zero, success=True, gate=self.gate, now=1_000)

        day_one_payload = {
            **self.empty_payload,
            "observation_scope": "check_and_notify_day_1",
        }
        day_one = decide_observation_delivery(day_one_payload, now=1_001)
        self.assertEqual(day_one.action, "forward")
        record_observation_result(day_one, success=True, gate=self.gate, now=1_001)

        self.assertEqual(
            decide_observation_delivery(self.empty_payload, now=100_000).action,
            "skip_success",
        )
        self.assertEqual(
            decide_observation_delivery(day_one_payload, now=100_001).action,
            "skip_success",
        )

    def test_failure_retries_are_bounded(self) -> None:
        first = decide_observation_delivery(self.empty_payload, now=2_000)
        record_observation_result(first, success=False, gate=None, now=2_000)

        self.assertEqual(
            decide_observation_delivery(self.empty_payload, now=2_030).action,
            "skip_retry",
        )
        self.assertEqual(
            decide_observation_delivery(self.empty_payload, now=2_119).action,
            "skip_retry",
        )
        self.assertEqual(
            decide_observation_delivery(self.empty_payload, now=2_120).action,
            "forward",
        )

    def test_real_change_bypasses_failure_backoff(self) -> None:
        first = decide_observation_delivery(self.empty_payload, now=2_000)
        record_observation_result(first, success=False, gate=None, now=2_000)

        changed = decide_observation_delivery(
            {
                **self.empty_payload,
                "healthy": False,
                "error": "upstream unavailable",
            },
            now=2_030,
        )
        self.assertEqual(changed.action, "forward")

    def test_failed_change_is_not_hidden_by_an_older_success(self) -> None:
        baseline = decide_observation_delivery(self.empty_payload, now=3_000)
        record_observation_result(baseline, success=True, gate=self.gate, now=3_000)

        changed = decide_observation_delivery(self.payload, now=3_010)
        self.assertEqual(changed.action, "forward")
        record_observation_result(changed, success=False, gate=self.gate, now=3_010)

        recent = decide_observation_delivery(self.payload, now=3_060)
        retry = decide_observation_delivery(self.payload, now=3_130)
        self.assertEqual(recent.action, "skip_retry")
        self.assertEqual(retry.action, "forward")

    def test_reads_legacy_state_without_restoring_venue_heartbeats(self) -> None:
        key, fingerprint = observation_identity(self.empty_payload)
        self.state_path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "entries": {
                        key: {
                            "fingerprint": fingerprint,
                            "last_attempt_at": 1_000,
                            "last_success_at": 1_000,
                            "gate": self.gate,
                        }
                    },
                    "venues": {
                        "szw": {
                            "last_attempt_at": 1_000,
                            "last_success_at": 1_000,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        decision = decide_observation_delivery(self.empty_payload, now=100_000)
        self.assertEqual(decision.action, "skip_success")
        self.assertEqual(decision.gate, self.gate)

    def test_gate_survives_process_independent_file_roundtrip(self) -> None:
        decision = decide_observation_delivery(self.empty_payload, now=4_000)
        record_observation_result(decision, success=True, gate=self.gate, now=4_000)

        self.assertEqual(cached_gate_for_venue("szw"), self.gate)
        stored = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["version"], 3)
        self.assertEqual(len(stored["entries"]), 1)
        self.assertNotIn("venues", stored)
        self.assertEqual(self.state_path.stat().st_mode & 0o777, 0o600)
