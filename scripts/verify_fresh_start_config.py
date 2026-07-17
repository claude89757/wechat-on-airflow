#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path


def compare_variables(
    expected: dict[str, str],
    getter: Callable[[str], str],
) -> dict[str, object]:
    missing_names: list[str] = []
    mismatched_names: list[str] = []
    for name, expected_value in sorted(expected.items()):
        try:
            actual_value = getter(name)
        except KeyError:
            missing_names.append(name)
            continue
        if actual_value != expected_value:
            mismatched_names.append(name)

    return {
        "ok": not missing_names and not mismatched_names,
        "expected_count": len(expected),
        "missing_names": missing_names,
        "mismatched_names": mismatched_names,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify imported Airflow Variables without printing their values."
    )
    parser.add_argument("expected_variables", type=Path)
    args = parser.parse_args()

    expected_value = json.loads(args.expected_variables.read_text(encoding="utf-8"))
    if not isinstance(expected_value, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in expected_value.items()
    ):
        raise SystemExit("expected variables must be a JSON object of string values")

    from airflow.models import Variable

    def get_variable(name: str) -> str:
        return str(Variable.get(name))

    report = compare_variables(expected_value, get_variable)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
