"""Busy is a pre-submission scheduling outcome, never an uncertain-send retry."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from fastapi.testclient import TestClient

import sender_agent.app as sender_app
from wechat_airflow.host_core import wechat_worker

BUSY = {
    "success": False,
    "error": "device_busy",
    "safe_to_retry": True,
    "submission_state": "not_submitted",
    "sent_count": 0,
}


@pytest.mark.parametrize("lock_kind", ["mutex", "device_lease"])
def test_busy_response_proves_no_ledger_or_ui_submission(monkeypatch, tmp_path, lock_kind):
    sender_app.reset_runtime_state()
    monkeypatch.setenv("WECHAT_ALLOWED_DEVICE_NAME", "test-device")
    monkeypatch.setenv("WECHAT_DEVICE_LOCK_DIR", str(tmp_path))
    monkeypatch.setenv("WECHAT_IDEMPOTENCY_PATH", str(tmp_path / "ledger.sqlite"))
    claim = Mock(side_effect=AssertionError("busy must not claim the ledger"))
    send = Mock(side_effect=AssertionError("busy must not submit to the UI"))
    monkeypatch.setattr(sender_app.ledger, "claim", claim)
    monkeypatch.setattr(sender_app, "send_text_messages", send)
    if lock_kind == "mutex":
        lock = Mock()
        lock.acquire.return_value = False
        monkeypatch.setattr(sender_app, "device_lock", lock)
    else:
        lease = Mock()
        lease.acquire.return_value = False
        monkeypatch.setattr(sender_app, "DeviceLease", Mock(return_value=lease))
    response = TestClient(sender_app.app).post(
        "/v1/wechat/send",
        json={
            "receiver": "test-group",
            "messages": ["test-message"],
            "device_name": "test-device",
            "idempotency_key": "test-id",
        },
    )
    assert response.status_code == 409
    assert response.json().items() >= BUSY.items()
    claim.assert_not_called()
    send.assert_not_called()
    if lock_kind == "mutex":
        lock.acquire.assert_called_once_with(timeout=sender_app.DEVICE_LOCK_WAIT_SECONDS)
        lock.release.assert_not_called()
    else:
        lease.acquire.assert_called_once_with(timeout=5)
    assert sender_app._device_lease is None


@pytest.fixture
def delivery(monkeypatch):
    row = {
        "id": "test-id",
        "venue_id": "tops",
        "receiver": "test-group",
        "device_name": "test-device",
        "outbound_message": "test-message",
        "attempt_count": wechat_worker.MAX_ATTEMPTS,
    }
    monkeypatch.setenv("DEPLOYMENT_COMMIT", "a" * 40)
    monkeypatch.setattr(wechat_worker, "delivery_guard", lambda: nullcontext(True))
    monkeypatch.setattr(
        wechat_worker,
        "sender_readiness",
        lambda: {"ok": True, "durableIdempotency": True, "deploymentCommit": "a" * 40},
    )
    monkeypatch.setattr(wechat_worker, "_prepare", lambda *_: True)
    monkeypatch.setattr(wechat_worker, "_first_value", lambda _: "http://isolated.invalid/send")
    finish, defer = Mock(), Mock()
    monkeypatch.setattr(wechat_worker, "_finish", finish)
    monkeypatch.setattr(wechat_worker, "_defer_device_busy", defer)
    return row, finish, defer


def test_proven_busy_defers_even_at_send_failure_budget(monkeypatch, delivery):
    row, finish, defer = delivery
    post = Mock(return_value=SimpleNamespace(status_code=409, json=lambda: dict(BUSY)))
    monkeypatch.setattr(wechat_worker.requests, "post", post)
    for _ in range(5):
        wechat_worker.deliver(row, "test-worker")
    assert defer.call_count == 5
    finish.assert_not_called()
    assert len({call.kwargs["json"]["idempotency_key"] for call in post.call_args_list}) == 1


@pytest.mark.parametrize(
    "overrides,status",
    [
        ({"safe_to_retry": False}, 409),
        ({"submission_state": "submission_unknown"}, 409),
        ({"sent_count": 1}, 409),
        ({"success": True}, 409),
        ({}, 500),
        ({"safe_to_retry": None, "submission_state": None, "sent_count": None}, 409),
    ],
)
def test_ambiguous_or_partial_busy_is_never_retried(monkeypatch, delivery, overrides, status):
    row, finish, defer = delivery
    monkeypatch.setattr(
        wechat_worker.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=status, json=lambda: {**BUSY, **overrides}
        ),
    )
    wechat_worker.deliver(row, "test-worker")
    finish.assert_called_once_with(row, "test-worker", "submission_unknown", "device_busy")
    defer.assert_not_called()


def test_real_pre_submission_failure_still_exhausts_send_budget(monkeypatch, delivery):
    row, finish, defer = delivery
    monkeypatch.setattr(
        wechat_worker.requests,
        "post",
        lambda *_args, **_kwargs: SimpleNamespace(
            status_code=500, json=lambda: {**BUSY, "error": "send_failed"}
        ),
    )
    wechat_worker.deliver(row, "test-worker")
    finish.assert_called_once_with(row, "test-worker", "failed", "send_failed")
    defer.assert_not_called()


def test_response_timeout_remains_unknown(monkeypatch, delivery):
    row, finish, defer = delivery
    monkeypatch.setattr(wechat_worker.requests, "post", Mock(side_effect=requests.ReadTimeout))
    wechat_worker.deliver(row, "test-worker")
    finish.assert_called_once_with(row, "test-worker", "submission_unknown", "ReadTimeout")
    defer.assert_not_called()
