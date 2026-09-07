"""Incident regressions: expired lines, durable ACKs and uncertain UI outcomes.

All data is synthetic. No test may contact a venue, mail provider or device.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import sender_agent.app as sender
from sender_agent import ledger
from wechat_airflow.host_core import wechat_worker
from wechat_airflow.host_core.wechat_queue import current_message
from wechat_airflow.notifications import webapp, wechat
from wechat_airflow.venues import dashahe_free_watcher as free
from wechat_sender import SendFailedError
from wechat_sender.appium_text_sender import SendProgress

SH = ZoneInfo("Asia/Shanghai")
STALE = "【大沙河免费场2号场】星期一(09-07)空场: 10:00-11:00"
FUTURE = "【大沙河免费场5号场】星期一(09-07)空场: 16:00-17:00"
SLOT = {"date": "2026-09-07", "court_name": "5号场", "start_time": "16:00", "end_time": "17:00"}
CURRENT = {
    "booking_date": date(2026, 9, 7),
    "court_name": "5号场",
    "start_time": "16:00",
    "end_time": "17:00",
    "event_key": "future",
}


def test_started_line_cannot_poison_valid_line_or_depend_on_order():
    for message in (STALE + "\n" + FUTURE, FUTURE + "\n" + STALE):
        assert current_message(message, [CURRENT]) == (FUTURE, ["future"], [STALE])


def test_all_stale_has_no_send_and_malformed_is_not_silently_hidden():
    assert current_message(STALE, []) == ("", [], [STALE])
    with pytest.raises(ValueError, match="invalid"):
        current_message("not an availability line\n" + FUTURE, [CURRENT])


def test_partly_covered_interval_does_not_invent_a_shorter_slot():
    long_line = FUTURE.replace("16:00-17:00", "15:00-17:00")
    assert current_message(long_line, [CURRENT]) == ("", [], [long_line])


@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-09-07T15:59:59+08:00", 1),
        ("2026-09-07T16:00:00+08:00", 0),
        ("2026-09-07T08:01:00+00:00", 0),
    ],
)
def test_filter_uses_shanghai_start_instant(instant, expected):
    assert len(free.future_slots([SLOT], now=datetime.fromisoformat(instant))) == expected


@pytest.mark.parametrize("data", [None, {}, {"list": None}, {"list": {}}, {"list": [None]}])
def test_calendar_protocol_error_is_not_healthy_empty(data):
    with pytest.raises(free.NswttProtocolError):
        free.ready_free_dates(data)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"placelist": []},
        {"placelist": [], "slicelist": None},
        {"placelist": [], "slicelist": [{}]},
    ],
)
def test_slot_protocol_error_is_not_unreleased_date(data):
    with pytest.raises(free.NswttProtocolError):
        free.extract_free_slots("2026-09-07", data)


def test_explicit_empty_collections_remain_healthy_empty():
    assert free.ready_free_dates({"list": []}) == []
    assert free.extract_free_slots("2026-09-07", {"placelist": [], "slicelist": []}) == (False, [])


def test_observation_requires_business_ack_even_when_http_succeeds():
    with (
        patch.object(webapp, "_host_token", return_value="isolated"),
        patch.object(webapp, "_get_variable", return_value="5"),
        patch.object(
            webapp.requests,
            "post",
            return_value=SimpleNamespace(
                raise_for_status=lambda: None, json=lambda: {"success": False}
            ),
        ),
    ):
        assert (
            webapp.publish_venue_observation("dsh_free", "free", [], healthy=True)["success"]
            is False
        )


def test_no_wechat_preclaim_when_observation_was_not_acknowledged():
    client = Mock()
    client.calendar_list.return_value = {"data": {"list": []}}
    with (
        patch.object(
            free, "_load_config_value", return_value={"app_version": "v", "cookie": "sid=isolated"}
        ),
        patch.object(free, "NswttClient", return_value=client),
        patch.object(free, "publish_venue_observation", return_value={"success": False}),
        patch.object(free, "_load_cache") as cache,
        patch.object(free, "send_wechat_text_to_chatrooms_best_effort") as send,
    ):
        assert free.run_check_dashahe_free_courts()["observation_published"] is False
    cache.assert_not_called()
    send.assert_not_called()


def test_partial_enqueue_ack_releases_only_the_stale_preclaim():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"success": True, "queued": 1, "rejected_lines": [STALE]},
    )
    with (
        patch.object(webapp, "_host_token", return_value="isolated"),
        patch.object(wechat.requests, "post", return_value=response),
        patch.object(wechat, "_get_variable", return_value="isolated-device"),
        patch.object(wechat, "_release_subscription_gate_dedupe") as release,
    ):
        result = wechat.send_wechat_text_to_chatrooms_best_effort(
            ["isolated-group"], STALE + "\n" + FUTURE, booking_venue_id="dsh_free"
        )
    assert result[0]["queued"] is True
    release.assert_called_once_with("dsh_free", STALE)


def test_sender_pre_submit_failure_is_retryable_but_click_failure_never_is(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_IDEMPOTENCY_PATH", str(tmp_path / "sender.sqlite3"))
    monkeypatch.setenv("WECHAT_ALLOWED_DEVICE_NAME", "test-device")
    sender.reset_runtime_state()
    request = {
        "receiver": "isolated-group",
        "device_name": "test-device",
        "messages": ["isolated"],
        "idempotency_key": "test-key",
    }
    client = TestClient(sender.app)
    with patch.object(sender, "send_text_messages", side_effect=SendFailedError("navigation")):
        response = client.post("/v1/wechat/send", json=request)
    assert response.json()["safe_to_retry"] is True
    assert response.json()["submission_state"] == "not_submitted"
    assert "navigation" not in response.text

    def uncertain(**kwargs):
        kwargs["progress"].submitting()
        raise SendFailedError("lost click response")

    with patch.object(sender, "send_text_messages", side_effect=uncertain) as send:
        response = client.post("/v1/wechat/send", json=request)
        assert response.json()["safe_to_retry"] is False
        assert response.json()["submission_state"] == "submission_unknown"
        repeated = client.post("/v1/wechat/send", json=request)
    assert repeated.status_code == 409
    assert send.call_count == 1


def test_preparing_crash_can_retry_but_old_dispatch_cannot(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_IDEMPOTENCY_PATH", str(tmp_path / "sender.sqlite3"))
    assert ledger.claim("new", "p", preparing=True)[0] == "claimed"
    assert ledger.claim("new", "p", preparing=True)[0] == "claimed"
    ledger.mark_submitting("new")
    ledger.finish("new", "not_submitted")  # Must not undo the boundary.
    assert ledger.claim("new", "p", preparing=True)[0] == "submission_unknown"
    ledger.claim("old", "p")
    assert ledger.claim("old", "p", preparing=True)[0] == "submission_unknown"


def test_submission_checkpoint_runs_before_ui_and_once_for_a_digest():
    check = Mock()
    progress = SendProgress(before_submit=check)
    progress.submitting()
    progress.submitting()
    check.assert_called_once()
    assert progress.submission_started


@contextmanager
def enabled_guard():
    yield True


@pytest.mark.parametrize(
    "safe,attempt,expected",
    [(True, 1, "retry"), (True, 3, "failed"), (False, 1, "submission_unknown")],
)
def test_worker_retries_only_proven_unsent_and_bounds_attempts(
    safe, attempt, expected, monkeypatch
):
    monkeypatch.setenv("DEPLOYMENT_COMMIT", "a" * 40)
    row = {
        "id": "id",
        "venue_id": "dsh_free",
        "receiver": "isolated",
        "device_name": "isolated",
        "outbound_message": FUTURE,
        "attempt_count": attempt,
    }
    payload = {
        "success": False,
        "error": "contact_not_found",
        "safe_to_retry": safe,
        "submission_state": "not_submitted" if safe else "submission_unknown",
        "sent_count": 0,
    }
    with (
        patch.object(wechat_worker, "delivery_guard", enabled_guard),
        patch.object(
            wechat_worker,
            "sender_readiness",
            return_value={"ok": True, "durableIdempotency": True, "deploymentCommit": "a" * 40},
        ),
        patch.object(wechat_worker, "_prepare", return_value=True),
        patch.object(
            wechat_worker, "_first_value", return_value="http://isolated.invalid/v1/wechat/send"
        ),
        patch.object(
            wechat_worker.requests,
            "post",
            return_value=SimpleNamespace(status_code=500, json=lambda: payload),
        ),
        patch.object(wechat_worker, "_finish") as finish,
    ):
        wechat_worker.deliver(row, "worker")
    finish.assert_called_once_with(row, "worker", expected, "contact_not_found")


def test_host_core_changes_cannot_bypass_the_full_lifecycle():
    import importlib.util
    import sys
    from pathlib import Path
    from unittest.mock import patch

    root = Path(__file__).parents[1]
    with patch.object(sys, "path", [str(root / "scripts"), *sys.path]):
        spec = importlib.util.spec_from_file_location(
            "host_scope", root / "scripts/host_core_release_scope.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    assert module.requires_host_core(["src/wechat_airflow/host_core/wechat_worker.py"])
    assert not module.requires_host_core(["webapp/src/CourtStudio.tsx"])
    ship = (root / ".github/workflows/production-ship.yml").read_text()
    assert "inputs.scope == 'all'" in ship
    assert "host_core_release_scope.py" in ship
    deploy = (root / ".github/workflows/production-release.yml").read_text()
    assert "host_core_release_scope.py" in deploy
