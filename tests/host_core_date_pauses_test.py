"""Real API, matching and delivery transactions against disposable PostgreSQL.

The shared fixture refuses non-test databases and prohibits all external I/O.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Event
from types import SimpleNamespace

import pytest
import requests

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
from wechat_airflow.host_core import date_pauses, service, worker
from wechat_airflow.host_core.domain import SHANGHAI, utc_now
from wechat_airflow.host_core.settings import load_settings
from wechat_airflow.host_core.weather import WeatherDecision

pytestmark = pytest.mark.skipif(not URL, reason="isolated PostgreSQL test URL not supplied")
PATH = PREFIX + "/notification-pauses"


def change(c, headers, dates, action="pause"):
    response = c.post(PATH, headers=headers, json={"action": action, "dates": dates})
    assert response.status_code == 200, response.text
    return response.json()


def test_date_pause_api_is_atomic_idempotent_and_receipt_scoped():
    with client() as c:
        assert c.get(PATH).status_code == 401
        assert c.post(PATH, json={"action": "pause", "dates": []}).status_code == 401
        first, other = identity(), identity("other@example.test")
        initial = c.get(PATH, headers=first).json()
        assert initial == {
            "pausedDates": [],
            "today": utc_now().astimezone(SHANGHAI).date().isoformat(),
            "timezone": "Asia/Shanghai",
        }
        today = date.fromisoformat(initial["today"])
        tomorrow = (today + timedelta(days=1)).isoformat()
        upper = (today + timedelta(days=365)).isoformat()
        first_change = change(c, first, [upper, tomorrow, tomorrow])
        assert first_change["changedDates"] == [tomorrow, upper]
        assert first_change["pausedDates"] == [tomorrow, upper]
        timestamps = sql(
            "SELECT updated_at FROM zacks.notification_date_pauses ORDER BY booking_date"
        )
        assert change(c, first, [tomorrow])["changedDates"] == []
        assert timestamps == sql(
            "SELECT updated_at FROM zacks.notification_date_pauses ORDER BY booking_date"
        )
        assert c.get(PATH, headers=other).json()["pausedDates"] == []
        assert change(c, other, [tomorrow], "resume")["changedDates"] == []
        bad_batches = [
            [today.isoformat(), "2026-02-30"],
            [today.isoformat(), (today - timedelta(days=1)).isoformat()],
            [today.isoformat(), (today + timedelta(days=366)).isoformat()],
            [today.isoformat(), "2026/11/02"],
            [tomorrow] * 32,
            [],
        ]
        for dates in bad_batches:
            assert (
                c.post(PATH, headers=first, json={"action": "pause", "dates": dates}).status_code
                == 400
            )
            assert c.get(PATH, headers=first).json()["pausedDates"] == [tomorrow, upper]
        assert (
            c.post(
                PATH,
                headers=first,
                json={
                    "action": "pause",
                    "dates": [today.isoformat()],
                    "email": "other@example.test",
                },
            ).status_code
            == 400
        )
        assert change(c, first, [tomorrow], "resume")["changedDates"] == [tomorrow]
        assert change(c, first, [tomorrow], "resume")["changedDates"] == []
        assert c.get(PATH, headers=first).json()["pausedDates"] == [upper]
        assert sql("SELECT count(*) AS n FROM zacks.notification_date_pauses")[0]["n"] == 2


def test_past_pauses_are_hidden_at_shanghai_midnight_without_deletion(monkeypatch):
    from datetime import UTC, datetime

    before = datetime(2026, 11, 2, 15, 59, tzinfo=UTC)
    monkeypatch.setattr(date_pauses, "utc_now", lambda: before)
    with client() as c:
        headers = identity()
        assert change(c, headers, ["2026-11-02"])["pausedDates"] == ["2026-11-02"]
        monkeypatch.setattr(date_pauses, "utc_now", lambda: before + timedelta(minutes=1))
        result = c.get(PATH, headers=headers).json()
    assert result["today"] == "2026-11-03"
    assert result["pausedDates"] == []
    assert sql("SELECT paused FROM zacks.notification_date_pauses")[0]["paused"] is True


def test_date_pause_covers_all_email_subscriptions_and_priority_but_not_others():
    payload = observation()
    day = payload["slots"][0]["date"]
    other_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    payload["slots"].append({**payload["slots"][0], "date": other_day})
    with client() as c:
        headers, second = identity(), identity("second@example.test")
        assert subscription(c, headers, venues=["tops", "gba"]).status_code == 201
        assert subscription(c, second).status_code == 201
        sql("""INSERT INTO zacks.user_delivery_tiers(email,tier,created_at,updated_at)
            VALUES('player@example.test','priority',now(),now())
            ON CONFLICT(email) DO UPDATE SET tier='priority'""")
        change(c, headers, [day])
        assert service.ingest_observation(payload)["matchedNotifications"] == 3
        gba = {**payload, "venue_id": "gba", "venue_name": "大湾区", "slots": [payload["slots"][0]]}
        assert service.ingest_observation(gba)["matchedNotifications"] == 0
        # A subscription created after the pause inherits the same preference.
        assert subscription(c, headers, start="17:00", end="22:00").status_code == 201
        assert service.ingest_observation(observation())["matchedNotifications"] == 0
        assert service.active_subscription_for_venue("tops") is True
        assert (
            c.post(PREFIX + "/email/send-code", json={"email": "player@example.test"}).status_code
            == 200
        )
    rows = sql("""SELECT email, booking_date FROM zacks.notification_outbox o
        JOIN zacks.observed_slots slot ON slot.event_key=o.event_key""")
    assert not any(
        r["email"] == "player@example.test" and r["booking_date"].isoformat() == day for r in rows
    )
    assert sql("SELECT status FROM zacks.system_email_outbox")[0]["status"] == "pending"


def test_pause_after_claim_releases_quota_and_resume_requires_fresh_observation(monkeypatch):
    sends = []

    def send(settings, recipient, subject, body, **kwargs):
        sends.append((subject, body))
        return SimpleNamespace(message_id="pause-test-provider", request_id="request")

    monkeypatch.setattr(worker, "send_template_email", send)
    with client() as c:
        headers = identity()
        make_pending(c, headers)
        enable_for_test()
        old_rows = claim()
        day = old_rows[0]["booking_date"].isoformat()
        old_seen = observation()
        sql("UPDATE zacks.notification_outbox SET created_at=now()-interval '1 hour'")
        original = sql("SELECT id,created_at FROM zacks.notification_outbox")[0]
        change(c, headers, [day])
        assert sql("SELECT status,last_error FROM zacks.notification_outbox")[0] == {
            "status": "cancelled",
            "last_error": "booking_date_paused",
        }
        assert sql("SELECT status FROM zacks.email_delivery_claims")[0]["status"] == "released"
        worker._complete_subscriber(old_rows, "test-worker")
        assert sends == []
        change(c, headers, [day], "resume")
        assert worker._next_subscriber_target() is None
        assert service.ingest_observation(old_seen)["matchedNotifications"] == 0
        assert service.ingest_observation(observation())["matchedNotifications"] == 1
        assert sql("SELECT id,created_at FROM zacks.notification_outbox")[0] == original
        assert sql("SELECT count(*) AS n FROM zacks.subscription_events")[0]["n"] == 1
        worker._expire_unusable()
        assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "pending"
        sql("UPDATE zacks.notification_outbox SET next_attempt_at=now()-interval '1 second'")
        fresh_rows = claim()
        # A stale holder with the same worker identity cannot expire or send the new claim.
        worker._complete_subscriber(old_rows, "test-worker")
        assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "processing"
        worker._complete_subscriber(fresh_rows, "test-worker")
        assert len(sends) == 1
        assert f"https://courts.zacks.vision/?pauseDate={day}" in sends[0][1]
        assert "example.test" not in sends[0][1]
        assert service.ingest_observation(observation())["matchedNotifications"] == 0
        assert worker._next_subscriber_target() is None


def test_resume_matches_same_slots_that_first_appeared_while_paused():
    old = observation()
    day = old["slots"][0]["date"]
    with client() as c:
        headers = identity()
        assert subscription(c, headers).status_code == 201
        change(c, headers, [day])
        assert service.ingest_observation(old)["matchedNotifications"] == 0
        change(c, headers, [day], "resume")
        # This consumes the current generation but is not a new court observation.
        assert service.ingest_observation(old)["matchedNotifications"] == 0
        assert service.ingest_observation(observation())["matchedNotifications"] == 1
    assert sql("SELECT count(*) AS n FROM zacks.notification_outbox")[0]["n"] == 1


@pytest.mark.parametrize("provider_unknown", [False, True])
def test_pause_resume_preserves_submitted_and_unknown_deliveries(monkeypatch, provider_unknown):
    sends = []

    def send(*args, **kwargs):
        sends.append(1)
        if provider_unknown:
            raise requests.ReadTimeout("simulated unknown")
        return SimpleNamespace(message_id="already-submitted", request_id="request")

    monkeypatch.setattr(worker, "send_template_email", send)
    with client() as c:
        headers = identity()
        make_pending(c, headers)
        enable_for_test()
        rows = claim()
        day = rows[0]["booking_date"].isoformat()
        worker._complete_subscriber(rows, "test-worker")
        before = sql("SELECT status,message_id,submitted_at FROM zacks.notification_outbox")
        claim_before = sql("SELECT status FROM zacks.email_delivery_claims")
        change(c, headers, [day])
        change(c, headers, [day], "resume")
        assert service.ingest_observation(observation())["matchedNotifications"] == 0
    assert sql("SELECT status,message_id,submitted_at FROM zacks.notification_outbox") == before
    assert sql("SELECT status FROM zacks.email_delivery_claims") == claim_before
    assert sends == [1]
    assert worker._next_subscriber_target() is None


def test_paused_date_is_rechecked_at_claim_and_dispatch(monkeypatch):
    monkeypatch.setattr(worker, "send_template_email", lambda *a, **k: pytest.fail("paused send"))
    with client() as c:
        headers = identity()
        make_pending(c, headers)
        enable_for_test()
        target = worker._next_subscriber_target()
        change(c, headers, [target["booking_date"]])
        # Simulate an older process leaving an unsent row: both guards still apply.
        sql("UPDATE zacks.notification_outbox SET status='pending',last_error=NULL")
        assert worker._next_subscriber_target() is None
        assert (
            worker._claim_subscriber_group(
                "test-worker",
                load_settings(),
                target,
                WeatherDecision(True, target["booking_date"], 0, 25, "test"),
            )
            == []
        )
        change(c, headers, [target["booking_date"]], "resume")
        rows = claim()
        sql("UPDATE zacks.notification_date_pauses SET paused=true")
        worker._complete_subscriber(rows, "test-worker")
    assert sql("SELECT status FROM zacks.notification_outbox")[0]["status"] == "expired"
    assert sql("SELECT status FROM zacks.email_delivery_claims")[0]["status"] == "released"


def test_pause_waits_for_inflight_send_and_keeps_provider_history(monkeypatch):
    started, finish, requested = Event(), Event(), Event()

    def send(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return SimpleNamespace(message_id="inflight-provider", request_id="request")

    monkeypatch.setattr(worker, "send_template_email", send)
    with client() as c:
        headers = identity()
        make_pending(c, headers)
        enable_for_test()
        rows = claim()
        day = rows[0]["booking_date"].isoformat()

        def pause():
            requested.set()
            with client() as other_client:
                return change(other_client, headers, [day])

        with ThreadPoolExecutor(max_workers=2) as pool:
            delivery = pool.submit(worker._complete_subscriber, rows, "test-worker")
            assert started.wait(5)
            mutation = pool.submit(pause)
            assert requested.wait(5)
            with pytest.raises(TimeoutError):
                mutation.result(timeout=0.1)
            finish.set()
            delivery.result(timeout=5)
            assert mutation.result(timeout=5)["changedDates"] == [day]
    assert sql("SELECT status,message_id FROM zacks.notification_outbox")[0] == {
        "status": "submitted",
        "message_id": "inflight-provider",
    }


def test_concurrent_pause_and_observation_leave_no_sendable_rows(monkeypatch):
    matched, finish, requested = Event(), Event(), Event()
    original_rules = service.observation_rules

    def delayed_rules(*args, **kwargs):
        rules = original_rules(*args, **kwargs)
        matched.set()
        assert finish.wait(5)
        return rules

    monkeypatch.setattr(service, "observation_rules", delayed_rules)
    with client() as c:
        headers = identity()
        assert subscription(c, headers).status_code == 201
        payload = observation()
        day = payload["slots"][0]["date"]

        def pause():
            requested.set()
            with client() as other_client:
                return change(other_client, headers, [day])

        with ThreadPoolExecutor(max_workers=2) as pool:
            poll = pool.submit(service.ingest_observation, payload)
            assert matched.wait(5)
            mutation = pool.submit(pause)
            assert requested.wait(5)
            with pytest.raises(TimeoutError):
                mutation.result(timeout=0.1)
            finish.set()
            poll.result(timeout=5)
            assert mutation.result(timeout=5)["changedDates"] == [day]
        assert service.ingest_observation(observation())["matchedNotifications"] == 0
    assert not sql(
        "SELECT id FROM zacks.notification_outbox WHERE status IN ('pending','retry','processing')"
    )
    assert worker._next_subscriber_target() is None
