"""Ideal-window send barrier and restore. No test may call a real provider."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
from types import SimpleNamespace

import pytest

from tests.host_core_postgres_test import (
    PREFIX,
    URL,
    claim,
    client,
    enable_for_test,
    identity,
    make_pending,
    observation,
    sql,
    subscription,
)
from tests.host_core_postgres_test import isolated_database as isolated_database
from wechat_airflow.host_core import service, worker
from wechat_airflow.host_core.domain import IDEAL_WINDOW_CHANGED

pytestmark = pytest.mark.skipif(not URL, reason="isolated PostgreSQL test URL not supplied")
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]


def _send_recorder(sends: list[str]):
    def send(settings, recipient, subject, body, **kwargs):
        sends.append(body)
        return SimpleNamespace(message_id="ideal-window-test", request_id="request")

    return send


def _patch(c, headers, subscription_id, body):
    response = c.patch(PREFIX + "/subscriptions/" + subscription_id, headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _pause(c, headers, day, action="pause"):
    response = c.post(
        PREFIX + "/notification-pauses",
        headers=headers,
        json={"action": action, "dates": [day]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _rows():
    return sql("""
        SELECT slot.start_time, o.status, o.last_error, o.message_id, o.submitted_at IS NOT NULL AS submitted
        FROM zacks.notification_outbox o
        JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
        ORDER BY slot.start_time
        """)


def _due():
    sql("UPDATE zacks.notification_outbox SET next_attempt_at = now() - interval '1 second'")


def test_claimed_window_change_cancels_unsent_mail_before_provider_send(monkeypatch):
    sends: list[str] = []
    monkeypatch.setattr(worker, "send_template_email", _send_recorder(sends))
    with client() as c:
        headers = identity()
        subscription_id = make_pending(c, headers)
        enable_for_test()
        claimed = claim()
        _patch(c, headers, subscription_id, {"preferencePreset": "weekday_noon"})
        worker._complete_subscriber(claimed, "test-worker")
    assert sends == []
    assert sql("SELECT status, last_error FROM zacks.notification_outbox") == [
        {"status": "cancelled", "last_error": IDEAL_WINDOW_CHANGED}
    ]
    assert sql("SELECT status FROM zacks.email_delivery_claims") == [{"status": "released"}]
    assert not sql("SELECT id FROM zacks.wechat_outbox")


def test_pre_send_recheck_cancels_window_mismatch_instead_of_expiring(monkeypatch):
    sends: list[str] = []
    monkeypatch.setattr(worker, "send_template_email", _send_recorder(sends))
    with client() as c:
        make_pending(c, identity())
        enable_for_test()
        claimed = claim()
    sql("UPDATE zacks.subscriptions SET start_time='12:00', end_time='14:00', weekday_mask=31")
    worker._complete_subscriber(claimed, "test-worker")
    assert sends == []
    assert sql("SELECT status, last_error FROM zacks.notification_outbox") == [
        {"status": "cancelled", "last_error": IDEAL_WINDOW_CHANGED}
    ]
    assert sql("SELECT status FROM zacks.email_delivery_claims") == [{"status": "released"}]


def test_overlapping_digest_row_still_sends_after_window_change(monkeypatch):
    sends: list[str] = []
    monkeypatch.setattr(worker, "send_template_email", _send_recorder(sends))
    payload = observation()
    payload["slots"].append(
        {**payload["slots"][0], "court_name": "2号场", "start_time": "20:00", "end_time": "21:00"}
    )
    with client() as c:
        headers = identity()
        created = subscription(c, headers, start="18:00", end="22:00")
        assert created.status_code == 201, created.text
        assert service.ingest_observation(payload)["matchedNotifications"] == 2
        enable_for_test()
        _due()
        claimed = claim()
        assert len(claimed) == 2
        _patch(
            c,
            headers,
            created.json()["id"],
            {"startTime": "19:30", "endTime": "22:00", "weekdays": ALL_DAYS},
        )
        worker._complete_subscriber(claimed, "test-worker")
    assert len(sends) == 1
    assert "20:00-21:00" in sends[0]
    assert "18:00-19:00" not in sends[0]
    assert _rows() == [
        {
            "start_time": "18:00",
            "status": "cancelled",
            "last_error": IDEAL_WINDOW_CHANGED,
            "message_id": None,
            "submitted": False,
        },
        {
            "start_time": "20:00",
            "status": "submitted",
            "last_error": None,
            "message_id": "ideal-window-test",
            "submitted": True,
        },
    ]
    assert sql("SELECT status FROM zacks.email_delivery_claims") == [{"status": "sent"}]


def test_submitted_or_live_attempt_rows_survive_a_nonoverlapping_window(monkeypatch):
    sends: list[str] = []
    monkeypatch.setattr(worker, "send_template_email", _send_recorder(sends))
    payload = observation()
    first = payload["slots"][0]
    payload["slots"] = [
        first,
        {**first, "court_name": "2号场", "start_time": "19:00", "end_time": "20:00"},
        {**first, "court_name": "3号场", "start_time": "20:00", "end_time": "21:00"},
    ]
    with client() as c:
        headers = identity()
        created = subscription(c, headers, start="18:00", end="22:00")
        assert service.ingest_observation(payload)["matchedNotifications"] == 3
        enable_for_test()
        _due()
        claimed = claim()
        by_start = {
            row["start_time"]: row["id"]
            for row in sql("""
                SELECT o.id, slot.start_time FROM zacks.notification_outbox o
                JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
                """)
        }
        sql(
            """
            UPDATE zacks.notification_outbox
            SET submitted_at = now(), message_id = 'already-accepted'
            WHERE id = :id
            """,
            {"id": by_start["18:00"]},
        )
        sql(
            """
            INSERT INTO zacks.delivery_attempts(id, channel, queue_ids, phase)
            VALUES (:id, 'subscriber_email', CAST(:ids AS jsonb), 'dispatching')
            """,
            {"id": str(uuid.uuid4()), "ids": json.dumps([by_start["19:00"]])},
        )
        sql(
            """
            INSERT INTO zacks.delivery_attempts(id, channel, queue_ids, phase)
            VALUES (:id, 'subscriber_email', CAST(:ids AS jsonb), 'retry')
            """,
            {"id": str(uuid.uuid4()), "ids": json.dumps([by_start["20:00"]])},
        )
        before = _rows()
        _patch(c, headers, created.json()["id"], {"preferencePreset": "weekday_noon"})
        after_patch = _rows()
        worker._complete_subscriber(claimed, "test-worker")
    assert sends == []
    assert before == [
        {
            "start_time": "18:00",
            "status": "processing",
            "last_error": None,
            "message_id": "already-accepted",
            "submitted": True,
        },
        {
            "start_time": "19:00",
            "status": "processing",
            "last_error": None,
            "message_id": None,
            "submitted": False,
        },
        {
            "start_time": "20:00",
            "status": "processing",
            "last_error": None,
            "message_id": None,
            "submitted": False,
        },
    ]
    assert after_patch == [
        before[0],
        before[1],
        {
            "start_time": "20:00",
            "status": "cancelled",
            "last_error": IDEAL_WINDOW_CHANGED,
            "message_id": None,
            "submitted": False,
        },
    ]
    assert _rows() == after_patch
    assert sql("SELECT status FROM zacks.email_delivery_claims") == [{"status": "reserved"}]


def test_dispatching_window_change_waits_until_the_vendor_call_finishes(monkeypatch):
    started, finish, requested = Event(), Event(), Event()
    sends: list[str] = []

    def send(settings, recipient, subject, body, **kwargs):
        sends.append(body)
        started.set()
        assert finish.wait(5)
        return SimpleNamespace(message_id="inflight-window", request_id="request")

    monkeypatch.setattr(worker, "send_template_email", send)
    with client() as c:
        headers = identity()
        subscription_id = make_pending(c, headers)
        enable_for_test()
        claimed = claim()

        def retarget():
            requested.set()
            with client() as other:
                return _patch(other, headers, subscription_id, {"preferencePreset": "weekday_noon"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            delivery = pool.submit(worker._complete_subscriber, claimed, "test-worker")
            assert started.wait(5)
            mutation = pool.submit(retarget)
            assert requested.wait(5)
            with pytest.raises(TimeoutError):
                mutation.result(timeout=0.1)
            finish.set()
            delivery.result(timeout=5)
            assert mutation.result(timeout=5)["windowChanged"] is True
    assert len(sends) == 1
    assert sql("SELECT status, message_id, last_error FROM zacks.notification_outbox") == [
        {"status": "submitted", "message_id": "inflight-window", "last_error": None}
    ]


def test_reopened_window_restores_on_a_later_fresh_observation(monkeypatch):
    sends: list[str] = []
    monkeypatch.setattr(worker, "send_template_email", _send_recorder(sends))
    original_seen = observation()
    day = original_seen["slots"][0]["date"]
    with client() as c:
        headers = identity()
        created = subscription(c, headers, start="18:00", end="21:00")
        assert service.ingest_observation(original_seen)["matchedNotifications"] == 1
        original = sql("SELECT id, created_at FROM zacks.notification_outbox")[0]
        event = sql("SELECT created_at FROM zacks.subscription_events")[0]
        narrowed = _patch(c, headers, created.json()["id"], {"preferencePreset": "weekday_noon"})
        assert narrowed["windowChanged"] is True
        assert sql("SELECT status, last_error FROM zacks.notification_outbox") == [
            {"status": "cancelled", "last_error": IDEAL_WINDOW_CHANGED}
        ]
        widened = _patch(
            c,
            headers,
            created.json()["id"],
            {"startTime": "18:00", "endTime": "21:00", "weekdays": ALL_DAYS},
        )
        assert widened["windowChanged"] is True
        assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "cancelled"
        assert service.ingest_observation(original_seen)["matchedNotifications"] == 0
        assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "cancelled"
        _pause(c, headers, day)
        paused_seen = observation()
        assert service.ingest_observation(paused_seen)["matchedNotifications"] == 0
        assert sql("SELECT status, last_error FROM zacks.notification_outbox") == [
            {"status": "cancelled", "last_error": IDEAL_WINDOW_CHANGED}
        ]
        _pause(c, headers, day, "resume")
        assert service.ingest_observation(paused_seen)["matchedNotifications"] == 0
        fresh = observation()
        assert service.ingest_observation(fresh)["matchedNotifications"] == 1
    restored = sql(
        "SELECT id, status, last_error, created_at, eligible_at FROM zacks.notification_outbox"
    )[0]
    assert restored["id"] == original["id"]
    assert restored["created_at"] == original["created_at"]
    assert restored["status"] == "pending"
    assert restored["last_error"] is None
    assert restored["eligible_at"] == datetime.fromisoformat(fresh["checked_at"])
    assert sql("SELECT created_at FROM zacks.subscription_events") == [event]
    assert sql("SELECT count(*) AS n FROM zacks.subscription_events")[0]["n"] == 1
    assert sends == []


def test_reopened_window_leaves_terminal_endings_unchanged(monkeypatch):
    sends: list[str] = []
    monkeypatch.setattr(worker, "send_template_email", _send_recorder(sends))
    payload = observation()
    base = payload["slots"][0]
    payload["slots"] = [
        {**base, "court_name": "已发", "start_time": "18:00", "end_time": "19:00"},
        {**base, "court_name": "未知", "start_time": "12:00", "end_time": "13:00"},
        {**base, "court_name": "过期", "start_time": "13:00", "end_time": "14:00"},
        {**base, "court_name": "下雨", "start_time": "14:00", "end_time": "15:00"},
        {**base, "court_name": "退订", "start_time": "15:00", "end_time": "16:00"},
        {**base, "court_name": "已盖章", "start_time": "16:00", "end_time": "17:00"},
        {**base, "court_name": "尝试中", "start_time": "17:00", "end_time": "18:00"},
        {**base, "court_name": "可恢复", "start_time": "19:00", "end_time": "20:00"},
    ]
    with client() as c:
        headers = identity()
        created = subscription(c, headers, start="08:00", end="22:00")
        assert service.ingest_observation(payload)["matchedNotifications"] == 8
        enable_for_test()
        _due()
        sql("""
            UPDATE zacks.notification_outbox o
            SET status = 'expired'
            FROM zacks.observed_slots slot
            WHERE slot.event_key = o.event_key AND slot.start_time <> '18:00'
            """)
        sent_rows = claim()
        assert len(sent_rows) == 1
        worker._complete_subscriber(sent_rows, "test-worker")
        sql(
            """
            UPDATE zacks.notification_outbox o
            SET status='pending', last_error=NULL, lease_owner=NULL, lease_until=NULL
            FROM zacks.observed_slots slot
            WHERE slot.event_key = o.event_key AND slot.start_time <> '18:00'
            """
        )
        by_start = {
            row["start_time"]: row["id"]
            for row in sql("""
                SELECT o.id, slot.start_time FROM zacks.notification_outbox o
                JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
                """)
        }
        sql(
            "UPDATE zacks.notification_outbox SET status='submission_unknown', last_error='ReadTimeout' WHERE id=:id",
            {"id": by_start["12:00"]},
        )
        sql(
            "UPDATE zacks.notification_outbox SET status='expired', last_error='not_eligible_at_dispatch' WHERE id=:id",
            {"id": by_start["13:00"]},
        )
        sql(
            "UPDATE zacks.notification_outbox SET status='suppressed', last_error='weather_suppressed:test' WHERE id=:id",
            {"id": by_start["14:00"]},
        )
        sql(
            "UPDATE zacks.notification_outbox SET status='cancelled', last_error='subscription_cancelled' WHERE id=:id",
            {"id": by_start["15:00"]},
        )
        calls_after_send = len(sends)
        _patch(c, headers, created.json()["id"], {"preferencePreset": "weekend_morning"})
        sql(
            "UPDATE zacks.notification_outbox SET submitted_at=now() WHERE id=:id",
            {"id": by_start["16:00"]},
        )
        sql(
            """
            INSERT INTO zacks.delivery_attempts(id, channel, queue_ids, phase)
            VALUES (:id, 'subscriber_email', CAST(:ids AS jsonb), 'submitted')
            """,
            {"id": str(uuid.uuid4()), "ids": json.dumps([by_start["17:00"]])},
        )
        frozen = _rows()
        _patch(
            c,
            headers,
            created.json()["id"],
            {"startTime": "08:00", "endTime": "22:00", "weekdays": ALL_DAYS},
        )
        assert _rows() == frozen
        assert (
            service.ingest_observation(observation(slots=payload["slots"]))["matchedNotifications"]
            == 1
        )
    restored = [row for row in _rows() if row["status"] == "pending"]
    assert restored == [
        {
            "start_time": "19:00",
            "status": "pending",
            "last_error": None,
            "message_id": None,
            "submitted": False,
        }
    ]
    endings = {row["start_time"]: (row["status"], row["last_error"]) for row in _rows()}
    assert endings["18:00"] == ("submitted", None)
    assert endings["12:00"] == ("submission_unknown", "ReadTimeout")
    assert endings["13:00"] == ("expired", "not_eligible_at_dispatch")
    assert endings["14:00"] == ("suppressed", "weather_suppressed:test")
    assert endings["15:00"] == ("cancelled", "subscription_cancelled")
    assert endings["16:00"][0] == "cancelled"
    assert endings["17:00"] == ("cancelled", IDEAL_WINDOW_CHANGED)
    assert len(sends) == calls_after_send == 1
