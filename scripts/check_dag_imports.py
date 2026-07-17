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
    components = {item["dag_id"]: item for item in manifest["active_dags"]}
    expected = set(components)
    dag_bag = DagBag(dag_folder=str(DAGS_DIR), safe_mode=False)
    actual = set(dag_bag.dag_ids)
    task_mismatches = {}
    file_mismatches = {}
    for dag_id in sorted(expected & actual):
        component = components[dag_id]
        dag = dag_bag.dags[dag_id]
        expected_tasks = sorted(component["tasks"])
        actual_tasks = sorted(dag.task_ids)
        if actual_tasks != expected_tasks:
            task_mismatches[dag_id] = {
                "expected": expected_tasks,
                "actual": actual_tasks,
            }

        relative_file = Path(component["file"])
        expected_file = (DAGS_DIR / relative_file.relative_to("dags")).resolve()
        actual_file = Path(dag.fileloc).resolve()
        if actual_file != expected_file:
            file_mismatches[dag_id] = {
                "expected": str(expected_file),
                "actual": str(actual_file),
            }

    payload = {
        "ok": (
            not dag_bag.import_errors
            and actual == expected
            and not task_mismatches
            and not file_mismatches
        ),
        "dag_count": len(actual),
        "expected_dag_count": len(expected),
        "missing_dags": sorted(expected - actual),
        "unexpected_dags": sorted(actual - expected),
        "task_mismatches": task_mismatches,
        "file_mismatches": file_mismatches,
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
