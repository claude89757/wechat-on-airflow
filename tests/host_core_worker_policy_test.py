from __future__ import annotations

from datetime import timedelta

from wechat_airflow.host_core.domain import utc_now
from wechat_airflow.host_core.worker import _provider_backoff, _retry_at


def test_provider_reconciliation_backoff_is_bounded() -> None:
    assert _provider_backoff(1) == timedelta(minutes=5)
    assert _provider_backoff(3) == timedelta(minutes=15)
    assert _provider_backoff(6) == timedelta(hours=1)
    assert _provider_backoff(9) == timedelta(hours=6)
    assert _provider_backoff(100) == timedelta(hours=6)


def test_send_retry_delay_never_exceeds_one_hour() -> None:
    delta = _retry_at(100) - utc_now()
    assert timedelta(minutes=59) < delta <= timedelta(hours=1, seconds=1)
