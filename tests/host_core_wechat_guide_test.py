"""Daily WeChat guide contracts against the isolated, no-delivery PostgreSQL DB."""

from __future__ import annotations

from datetime import UTC, timedelta

import pytest

from tests.host_core_postgres_test import (
    URL,
    client,
    identity,
    observation,
    sql,
    subscription,
)
from tests.host_core_postgres_test import (
    isolated_database as isolated_database,
)
from wechat_airflow.host_core import database, service, wechat_queue, wechat_worker
from wechat_airflow.host_core.domain import SHANGHAI, VENUES, utc_now
from wechat_airflow.notifications.booking_links import TOPS_PROGRAM

pytestmark = pytest.mark.skipif(not URL, reason="isolated PostgreSQL test URL not supplied")
WORKER = "guide-test-worker"


@pytest.fixture(autouse=True)
def subscribed_venues(request):
    request.getfixturevalue("isolated_database")
    with client() as api_client:
        response = subscription(api_client, identity(), venues=["tops", "szw"])
        assert response.status_code == 201, response.text


@pytest.fixture
def morning():
    return utc_now().astimezone(SHANGHAI).replace(hour=8, minute=0, second=0, microsecond=0)


def queue_alert(*, court="1号场", receiver="test-only-group-a", venue="tops"):
    payload = observation(scope=f"guide-{court}")
    payload.update(venue_id=venue, venue_name=VENUES[venue])
    payload["slots"][0]["court_name"] = court
    service.ingest_observation(payload)
    day = payload["slots"][0]["date"]
    result = wechat_queue.enqueue(
        {
            "venue_id": venue,
            "receivers": [receiver],
            "device_name": "test-device",
            "message": f"【{court}】星期日({day[5:]})空场: 18:00-19:00",
            "source": "guide-test",
        }
    )
    assert result["queued"] == 1
    row = wechat_worker._claim(WORKER)
    assert row is not None and row["id"] == result["ids"][0]
    return row


def prepare_at(monkeypatch, row, now):
    monkeypatch.setattr(wechat_worker, "utc_now", lambda: now)
    assert wechat_worker._prepare(row, WORKER)
    saved = sql("SELECT * FROM zacks.wechat_outbox WHERE id=:id", {"id": row["id"]})[0]
    assert saved["status"] == "dispatching"
    assert saved["outbound_message"] == row["outbound_message"]
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in saved["message"]
    return row["outbound_message"]


def finish_at(row, status, now):
    wechat_worker._finish(row, WORKER, status)
    sql(
        """UPDATE zacks.wechat_outbox SET updated_at=:now,
        sent_at=CASE WHEN status='sent' THEN :now ELSE sent_at END WHERE id=:id""",
        {"id": row["id"], "now": now},
    )


def reclaim(row):
    sql(
        "UPDATE zacks.wechat_outbox SET next_attempt_at=now()-interval '1 second' WHERE id=:id",
        {"id": row["id"]},
    )
    retried = wechat_worker._claim(WORKER)
    assert retried is not None and retried["id"] == row["id"]
    return retried


def test_first_morning_message_is_per_group_across_venues_and_database_reconnect(
    monkeypatch, morning
):
    first = queue_alert()
    outbound = prepare_at(monkeypatch, first, morning)
    assert outbound.endswith("\n\n" + wechat_worker.EMAIL_SUBSCRIPTION_GUIDE)
    assert TOPS_PROGRAM.link in outbound
    finish_at(first, "sent", morning)

    # A fresh DB connection still sees the durable send; no process-local daily flag.
    database.reset_engine_for_test()
    second = queue_alert(court="2号场", venue="szw")
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in prepare_at(
        monkeypatch, second, morning + timedelta(minutes=1)
    )
    finish_at(second, "sent", morning + timedelta(minutes=1))

    other_group = queue_alert(court="3号场", receiver="test-only-group-b")
    assert prepare_at(monkeypatch, other_group, morning).endswith(
        wechat_worker.EMAIL_SUBSCRIPTION_GUIDE
    )


def test_safe_retry_keeps_payload_until_another_alert_succeeds(monkeypatch, morning):
    first = queue_alert()
    original = prepare_at(monkeypatch, first, morning)
    finish_at(first, "retry", morning)
    first = reclaim(first)
    assert prepare_at(monkeypatch, first, morning + timedelta(seconds=15)) == original
    finish_at(first, "retry", morning + timedelta(seconds=15))

    # The first attempt was explicitly not submitted, so another eligible alert can guide.
    second = queue_alert(court="2号场", venue="szw")
    assert prepare_at(monkeypatch, second, morning + timedelta(seconds=20)).endswith(
        wechat_worker.EMAIL_SUBSCRIPTION_GUIDE
    )
    finish_at(second, "sent", morning + timedelta(seconds=20))

    first = reclaim(first)
    outbound = prepare_at(monkeypatch, first, morning + timedelta(seconds=30))
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in outbound
    assert TOPS_PROGRAM.link in outbound


@pytest.mark.parametrize("status", ["dispatching", "submission_unknown"])
def test_uncertain_guide_suppresses_duplicates_but_not_the_next_morning(
    monkeypatch, morning, status
):
    first = queue_alert()
    assert prepare_at(monkeypatch, first, morning).endswith(wechat_worker.EMAIL_SUBSCRIPTION_GUIDE)
    if status == "submission_unknown":
        finish_at(first, status, morning)

    second = queue_alert(court="2号场")
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in prepare_at(
        monkeypatch, second, morning + timedelta(minutes=1)
    )
    finish_at(second, "failed", morning + timedelta(minutes=1))

    # Reconciliation can advance updated_at without changing the original send day.
    tomorrow = morning + timedelta(days=1)
    sql(
        "UPDATE zacks.wechat_outbox SET updated_at=:now WHERE id=:id",
        {"id": first["id"], "now": tomorrow},
    )
    database.reset_engine_for_test()
    third = queue_alert(court="3号场")
    assert prepare_at(monkeypatch, third, tomorrow).endswith(wechat_worker.EMAIL_SUBSCRIPTION_GUIDE)


def test_overnight_unknown_without_a_guide_does_not_consume_the_morning(monkeypatch, morning):
    overnight = morning.replace(hour=1)
    first = queue_alert()
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in prepare_at(monkeypatch, first, overnight)
    finish_at(first, "submission_unknown", overnight)
    sql(
        "UPDATE zacks.wechat_outbox SET created_at=:created, updated_at=:updated WHERE id=:id",
        {"id": first["id"], "created": overnight, "updated": morning},
    )
    second = queue_alert(court="2号场")
    assert prepare_at(monkeypatch, second, morning).endswith(wechat_worker.EMAIL_SUBSCRIPTION_GUIDE)


@pytest.mark.parametrize(
    ("hour", "minute", "second", "expected"),
    [(5, 59, 59, False), (6, 0, 0, True), (11, 59, 59, True), (12, 0, 0, False)],
)
def test_morning_boundaries_use_shanghai_time(monkeypatch, morning, hour, minute, second, expected):
    local = morning.replace(hour=hour, minute=minute, second=second)
    # Pass UTC to ensure the process or caller timezone cannot shift the morning window.
    now = local.astimezone(UTC)
    row = queue_alert()
    outbound = prepare_at(monkeypatch, row, now)
    assert (wechat_worker.EMAIL_SUBSCRIPTION_GUIDE in outbound) is expected


def test_retry_after_noon_removes_the_guide_and_keeps_booking_footer(monkeypatch, morning):
    before_noon = morning.replace(hour=11, minute=59, second=50)
    first = queue_alert()
    assert prepare_at(monkeypatch, first, before_noon).endswith(
        wechat_worker.EMAIL_SUBSCRIPTION_GUIDE
    )
    finish_at(first, "retry", before_noon)
    first = reclaim(first)
    outbound = prepare_at(monkeypatch, first, morning.replace(hour=12))
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in outbound
    assert TOPS_PROGRAM.link in outbound


def test_invalid_availability_does_not_consume_the_daily_guide(monkeypatch, morning):
    first = queue_alert()
    service.ingest_observation(observation(scope="guide-1号场", slots=[]))
    monkeypatch.setattr(wechat_worker, "utc_now", lambda: morning)
    assert wechat_worker._prepare(first, WORKER) is False
    saved = sql("SELECT status,outbound_message FROM zacks.wechat_outbox WHERE id=:id", first)[0]
    assert saved == {"status": "expired", "outbound_message": None}

    second = queue_alert(court="2号场")
    assert prepare_at(monkeypatch, second, morning).endswith(wechat_worker.EMAIL_SUBSCRIPTION_GUIDE)


def test_existing_morning_send_without_guide_does_not_add_a_second_first_message(
    monkeypatch, morning
):
    first = queue_alert()
    # Represents a message from the previous runtime, or one started before 06:00.
    prepare_at(monkeypatch, first, morning.replace(hour=5))
    finish_at(first, "sent", morning)
    second = queue_alert(court="2号场")
    assert wechat_worker.EMAIL_SUBSCRIPTION_GUIDE not in prepare_at(
        monkeypatch, second, morning + timedelta(minutes=1)
    )
