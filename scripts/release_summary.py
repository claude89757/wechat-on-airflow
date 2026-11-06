#!/usr/bin/env python3
"""Say in one place what a business release did and what to do next."""

from __future__ import annotations

import json
import os
from typing import Any

STAGES = ("gate", "airflow", "sender", "host_core", "activate", "activate_retry", "observe")
UNAFFECTED = "Notifications are unaffected: the old consumers are still delivering."
EFFECTS = {
    "gate": UNAFFECTED,
    "airflow": "The old consumers are still delivering, but venue checks may be interrupted.",
    "sender": UNAFFECTED,
    "host_core": "Delivery may be paused. Check deliveryOwner at /api/healthz.",
    "activate": "Delivery is paused until activation succeeds.",
    "observe": "Delivery is running; only the post-release health check failed.",
}


def failed_stage(results: dict[str, str]) -> str | None:
    if results.get("activate_retry") == "success":
        results = {**results, "activate": "success"}
    for stage in STAGES:
        if results.get(stage) in {"failure", "cancelled"}:
            return "activate" if stage == "activate_retry" else stage
    return None


def report(results: dict[str, str], run_id: str, target: str) -> dict[str, Any]:
    stage = failed_stage(results)
    return {
        "event": "release_summary",
        "ok": stage is None,
        "targetCommit": target,
        "failedStage": stage,
        "effect": EFFECTS[stage] if stage else "Released; delivery is running.",
        "stages": {name: results.get(name, "unknown") for name in STAGES},
        "nextStep": (
            f"Read `gh run view {run_id} --log-failed`. If the cause was transient, resume "
            f"with `make release-resume RUN_ID={run_id}`. If it needs a code fix, merge the "
            "fix and run `make release`, which also works while delivery is paused."
            if stage
            else None
        ),
    }


def main() -> None:
    needs = json.loads(os.environ["RESULTS"])
    result = report(
        {name: value.get("result", "unknown") for name, value in needs.items()},
        os.environ["RUN_ID"],
        os.environ["TARGET_COMMIT"],
    )
    print(json.dumps(result, sort_keys=True))
    lines = [
        f"## Release {'succeeded' if result['ok'] else 'failed'}: `{result['targetCommit']}`",
        "",
        result["effect"],
    ]
    if result["nextStep"]:
        lines += ["", result["nextStep"]]
    lines += ["", "| Stage | Result |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in result["stages"].items()]
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
