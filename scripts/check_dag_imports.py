#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from airflow.dag_processing.dagbag import DagBag

ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = Path("/opt/airflow/dags") if Path("/opt/airflow/dags").is_dir() else ROOT / "dags"
MANIFEST = ROOT / "config" / "active-components.yaml"


def main() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    expected = {item["dag_id"] for item in manifest["active_dags"]}
    dag_bag = DagBag(dag_folder=str(DAGS_DIR), safe_mode=False)
    actual = set(dag_bag.dag_ids)
    payload = {
        "ok": not dag_bag.import_errors and actual == expected,
        "dag_count": len(actual),
        "expected_dag_count": len(expected),
        "missing_dags": sorted(expected - actual),
        "unexpected_dags": sorted(actual - expected),
        "import_errors": {
            str(path): str(error) for path, error in sorted(dag_bag.import_errors.items())
        },
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc), "component": "dag_import_check"},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise
