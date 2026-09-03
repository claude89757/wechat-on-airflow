from __future__ import annotations

from wechat_airflow.host_core.migration import _integer


def test_migration_integer_preserves_legitimate_zero_values() -> None:
    assert _integer(0, 7) == 0
    assert _integer("0", 7) == 0
    assert _integer(False, 7) == 0
    assert _integer(True, 7) == 1
    assert _integer(14, 7) == 14
    assert _integer("14", 7) == 14
    assert _integer(None, 7) == 7
    assert _integer("", 7) == 7
    assert _integer("invalid", 7) == 7
