from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "recovery_release_contract", ROOT / "scripts/release_contract.py"
)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def baseline():
    return {
        "version": "0.9.1",
        "target_commit": "a" * 40,
        "scope": "all",
        "include_sender": True,
        "runtime_commit": "b" * 40,
        "control_updated_at": "2026-11-01T02:55:08.601801+00:00",
        "delivery_enabled": True,
        "wechat_enabled": False,
    }


def test_recovery_accepts_exact_recorded_email_active_baseline():
    CONTRACT.validate_recovery(**baseline())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_commit", "main"),
        ("runtime_commit", "HEAD"),
        ("runtime_commit", "a" * 40),
        ("scope", "webapp"),
        ("include_sender", False),
        ("delivery_enabled", False),
        ("wechat_enabled", True),
        ("version", "0.7.0"),
        ("control_updated_at", ""),
        ("control_updated_at", "2026-11-01"),
        ("control_updated_at", "2026-11-01T10:55:08+08:00"),
        ("control_updated_at", "2026-02-31T02:55:08Z"),
    ],
)
def test_recovery_rejects_unreviewed_or_inconsistent_baseline(field, value):
    values = baseline()
    values[field] = value
    with pytest.raises(CONTRACT.ContractError):
        CONTRACT.validate_recovery(**values)


def test_normal_ship_remains_outside_recovery_mode():
    values = baseline()
    values.update(
        runtime_commit="",
        control_updated_at="",
        delivery_enabled=False,
        wechat_enabled=False,
        scope="auto",
        include_sender=False,
    )
    CONTRACT.validate_recovery(**values)
