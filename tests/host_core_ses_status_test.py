from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wechat_airflow.host_core.tencent_ses import normalize_status


@pytest.mark.parametrize(
    "code",
    [
        1001,
        1002,
        1003,
        1004,
        1005,
        1006,
        1007,
        1008,
        1009,
        1010,
        1011,
        1013,
        3007,
        3008,
        3009,
        3010,
        3014,
        3020,
        3024,
        3030,
        3033,
    ],
)
@pytest.mark.parametrize("as_string", [False, True])
def test_documented_processing_failures_are_terminal(code, as_string):
    state, reason, _ = normalize_status(
        {"SendStatus": str(code) if as_string else code, "DeliverStatus": 0}
    )
    assert state == "failed"
    assert str(code) in reason


@pytest.mark.parametrize("deliver", [0, 8, "0", "8"])
def test_queued_or_delayed_is_never_delivered_from_timestamp_alone(deliver):
    state, _, _ = normalize_status(
        {"SendStatus": 0, "DeliverStatus": deliver, "DeliverTime": 1788609600}
    )
    assert state == "pending"


@pytest.mark.parametrize("deliver", [2, 3, "2", "3"])
def test_recipient_rejection_preserves_reason(deliver):
    state, reason, _ = normalize_status(
        {"SendStatus": 0, "DeliverStatus": deliver, "DeliverMessage": "synthetic rejection"}
    )
    assert state == "failed"
    assert reason == "synthetic rejection"


def test_explicit_delivery_and_timestamp_are_preserved():
    state, _, delivered_at = normalize_status(
        {"SendStatus": 0, "DeliverStatus": 1, "DeliverTime": 1788609600}
    )
    assert state == "delivered"
    assert delivered_at == datetime.fromtimestamp(1788609600, UTC)


@pytest.mark.parametrize("record", [None, {}, {"SendStatus": 2001}, {"SendStatus": "2001"}])
def test_missing_provider_record_is_not_proof_of_delivery_or_failure(record):
    assert normalize_status(record)[0] == "pending"


def test_malformed_timestamp_does_not_hide_explicit_provider_failure():
    state, reason, delivered_at = normalize_status(
        {"SendStatus": 1010, "DeliverStatus": 0, "DeliverTime": "9" * 100}
    )
    assert state == "failed"
    assert "1010" in reason
    assert delivered_at is None
