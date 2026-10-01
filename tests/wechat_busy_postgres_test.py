"""Exercise busy deferral against the guarded disposable PostgreSQL fixture."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.host_core_postgres_test import (
    URL,
    client,
    enable_for_test,
    identity,
    isolated_database,
    observation,
    sql,
    subscription,
)
from tests.wechat_busy_deferral_test import BUSY
from wechat_airflow.host_core import service, wechat_queue, wechat_worker
from wechat_airflow.host_core.domain import utc_now

pytestmark = [
    pytest.mark.skipif(not URL, reason="isolated PostgreSQL test URL not supplied"),
    pytest.mark.usefixtures("isolated_database"),
]
# Register the imported, destructive-fixture safety guard for this module too.
assert isolated_database


def queue_for_test(monkeypatch, previous_attempts=0):
    with client() as c:
        assert subscription(c, identity()).status_code == 201
        payload = observation()
        service.ingest_observation(payload)
    day = payload["slots"][0]["date"]
    wechat_queue.enqueue(
        {
            "venue_id": "tops",
            "receivers": ["test-only-group"],
            "device_name": "test-device",
            "message": f"【1号场】星期日({day[5:]})空场: 18:00-19:00",
        }
    )
    enable_for_test()
    sql(
        "UPDATE zacks.wechat_outbox SET attempt_count=:attempts",
        {"attempts": previous_attempts},
    )
    monkeypatch.setattr(
        wechat_worker,
        "sender_readiness",
        lambda: {"ok": True, "deploymentCommit": "a" * 40, "durableIdempotency": True},
    )
    monkeypatch.setattr(wechat_worker, "_first_value", lambda _: "http://isolated.invalid/send")


@pytest.mark.parametrize("previous_attempts", [0, 2])
def test_busy_waits_beyond_three_claims_then_sends_with_same_identity(
    monkeypatch, previous_attempts
):
    queue_for_test(monkeypatch, previous_attempts)
    expires = sql("SELECT expires_at FROM zacks.wechat_outbox")[0]["expires_at"]
    requests = []
    response = dict(BUSY)

    def post(_url, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(
            status_code=200 if response.get("success") else 409, json=lambda: response
        )

    monkeypatch.setattr(wechat_worker.requests, "post", post)
    for _ in range(5):
        row = wechat_worker._claim("test-worker")
        assert row["attempt_count"] == previous_attempts + 1
        wechat_worker.deliver(row, "test-worker")
        saved = sql("SELECT * FROM zacks.wechat_outbox")[0]
        assert saved["status"] == "retry"
        assert saved["attempt_count"] == previous_attempts
        assert saved["expires_at"] == expires
        assert utc_now() < saved["next_attempt_at"] <= utc_now() + timedelta(seconds=15)
        assert saved["lease_owner"] is None and saved["lease_until"] is None
        assert wechat_worker._claim("test-worker") is None
        sql("UPDATE zacks.wechat_outbox SET next_attempt_at=now()-interval '1 second'")
    response = {"success": True, "sent_count": 1}
    wechat_worker.deliver(wechat_worker._claim("test-worker"), "test-worker")
    saved = sql("SELECT status,attempt_count FROM zacks.wechat_outbox")[0]
    assert saved == {"status": "sent", "attempt_count": previous_attempts + 1}
    assert len({request["idempotency_key"] for request in requests}) == 1
    assert wechat_worker._claim("test-worker") is None


def test_busy_backoff_is_capped_and_expired_work_is_never_claimed(monkeypatch):
    queue_for_test(monkeypatch)
    row = wechat_worker._claim("test-worker")
    assert wechat_worker._prepare(row, "test-worker")
    sql("UPDATE zacks.wechat_outbox SET expires_at=now()+interval '5 seconds'")
    wechat_worker._defer_device_busy(row, "test-worker")
    saved = sql("SELECT status,next_attempt_at,expires_at FROM zacks.wechat_outbox")[0]
    assert saved["status"] == "retry"
    assert saved["next_attempt_at"] == saved["expires_at"]
    sql("UPDATE zacks.wechat_outbox SET expires_at=now()-interval '1 second'")
    assert wechat_worker._claim("test-worker") is None
    assert sql("SELECT status FROM zacks.wechat_outbox")[0]["status"] == "expired"


def test_busy_response_after_ttl_expires_immediately_without_refunding_prior_failures(monkeypatch):
    queue_for_test(monkeypatch, previous_attempts=2)
    row = wechat_worker._claim("test-worker")
    assert wechat_worker._prepare(row, "test-worker")
    sql("UPDATE zacks.wechat_outbox SET expires_at=now()-interval '1 second'")
    wechat_worker._defer_device_busy(row, "test-worker")
    saved = sql("SELECT status,attempt_count,lease_owner FROM zacks.wechat_outbox")[0]
    assert saved == {"status": "expired", "attempt_count": 2, "lease_owner": None}
    assert wechat_worker._claim("test-worker") is None


@pytest.mark.parametrize(
    "state,owner", [("dispatching", "other-worker"), ("submission_unknown", "test-worker")]
)
def test_busy_refund_cannot_change_another_lease_or_unknown_outcome(monkeypatch, state, owner):
    queue_for_test(monkeypatch, previous_attempts=2)
    row = wechat_worker._claim("test-worker")
    sql(
        "UPDATE zacks.wechat_outbox SET status=:status,lease_owner=:owner",
        {"status": state, "owner": owner},
    )
    wechat_worker._defer_device_busy(row, "test-worker")
    saved = sql("SELECT status,attempt_count,lease_owner FROM zacks.wechat_outbox")[0]
    assert saved == {"status": state, "attempt_count": 3, "lease_owner": owner}


def test_busy_retry_rechecks_current_availability_before_any_send(monkeypatch):
    queue_for_test(monkeypatch)
    row = wechat_worker._claim("test-worker")
    assert wechat_worker._prepare(row, "test-worker")
    wechat_worker._defer_device_busy(row, "test-worker")
    # Repeated completion cannot refund the previous genuine send-failure budget.
    wechat_worker._defer_device_busy(row, "test-worker")
    assert sql("SELECT attempt_count FROM zacks.wechat_outbox")[0]["attempt_count"] == 0
    service.ingest_observation(observation(slots=[]))
    sql("UPDATE zacks.wechat_outbox SET next_attempt_at=now()-interval '1 second'")
    monkeypatch.setattr(
        wechat_worker.requests, "post", lambda *_a, **_k: pytest.fail("stale busy intent sent")
    )
    wechat_worker.deliver(wechat_worker._claim("test-worker"), "test-worker")
    assert sql("SELECT status FROM zacks.wechat_outbox")[0]["status"] == "expired"


def test_actual_failures_keep_three_attempt_limit_across_busy_deferrals(monkeypatch):
    queue_for_test(monkeypatch)
    for error in ["send_failed", "send_failed", *(["device_busy"] * 5), "send_failed"]:
        monkeypatch.setattr(
            wechat_worker.requests,
            "post",
            lambda *_a, error=error, **_k: SimpleNamespace(
                status_code=409 if error == "device_busy" else 500,
                json=lambda: {**BUSY, "error": error},
            ),
        )
        row = wechat_worker._claim("test-worker")
        assert row
        wechat_worker.deliver(row, "test-worker")
        sql("UPDATE zacks.wechat_outbox SET next_attempt_at=now()-interval '1 second'")
    assert sql("SELECT status,attempt_count FROM zacks.wechat_outbox")[0] == {
        "status": "failed",
        "attempt_count": 3,
    }
    assert wechat_worker._claim("test-worker") is None


def test_concurrent_busy_completions_refund_only_the_current_claim(monkeypatch):
    queue_for_test(monkeypatch, previous_attempts=2)
    row = wechat_worker._claim("test-worker")
    assert wechat_worker._prepare(row, "test-worker")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: wechat_worker._defer_device_busy(row, "test-worker"), range(2)))
    assert sql("SELECT status,attempt_count FROM zacks.wechat_outbox")[0] == {
        "status": "retry",
        "attempt_count": 2,
    }


def test_busy_retry_rechecks_cancelled_subscription_before_any_send(monkeypatch):
    queue_for_test(monkeypatch)
    row = wechat_worker._claim("test-worker")
    assert wechat_worker._prepare(row, "test-worker")
    wechat_worker._defer_device_busy(row, "test-worker")
    sql("UPDATE zacks.subscriptions SET active=false")
    sql("UPDATE zacks.wechat_outbox SET next_attempt_at=now()-interval '1 second'")
    monkeypatch.setattr(
        wechat_worker.requests, "post", lambda *_a, **_k: pytest.fail("cancelled intent sent")
    )
    wechat_worker.deliver(wechat_worker._claim("test-worker"), "test-worker")
    assert sql("SELECT status FROM zacks.wechat_outbox")[0]["status"] == "cancelled"
