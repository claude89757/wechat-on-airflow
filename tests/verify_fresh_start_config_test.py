from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import verify_fresh_start_config  # noqa: E402


def test_verifier_uses_airflow_3_sdk_variable_api() -> None:
    source = (SCRIPTS_DIR / "verify_fresh_start_config.py").read_text(encoding="utf-8")

    assert "from airflow.sdk import Variable" in source
    assert "from airflow.models import Variable" not in source


def test_compare_variables_redacts_values_and_reports_names_only() -> None:
    def getter(name: str) -> str:
        values = {"matching": "expected", "mismatched": "actual-secret"}
        if name == "missing":
            raise KeyError(name)
        return values[name]

    report = verify_fresh_start_config.compare_variables(
        {
            "matching": "expected",
            "mismatched": "expected-secret",
            "missing": "missing-secret",
        },
        getter,
    )

    assert report == {
        "ok": False,
        "expected_count": 3,
        "missing_names": ["missing"],
        "mismatched_names": ["mismatched"],
    }
    assert "actual-secret" not in repr(report)
    assert "expected-secret" not in repr(report)
    assert "missing-secret" not in repr(report)
