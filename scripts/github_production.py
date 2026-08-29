#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import uuid

from _ops import REPO_ROOT, OpsError, run

WORKFLOWS = {
    "airflow": "production-airflow.yml",
    "sender": "production-wechat-sender.yml",
    "webapp": "production-webapp.yml",
}


def discover_run(workflow: str, title: str, timeout_seconds: int = 90) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = run(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                workflow,
                "--event",
                "workflow_dispatch",
                "--limit",
                "30",
                "--json",
                "databaseId,displayTitle",
            ]
        )
        for item in json.loads(result.stdout):
            if item.get("displayTitle") == title:
                return int(item["databaseId"])
        time.sleep(2)
    raise OpsError("GitHub did not expose the dispatched workflow run in time")


def dispatch(
    component: str,
    operation: str,
    target_commit: str,
    *,
    confirm_real_send: bool = False,
    probe_target_membership: str = "",
) -> None:
    workflow = WORKFLOWS[component]
    request_id = uuid.uuid4().hex
    title = f"production/{component}/{operation}/{request_id}"
    command = [
        "gh",
        "workflow",
        "run",
        workflow,
        "--ref",
        "main",
        "-f",
        f"operation={operation}",
        "-f",
        f"target_commit={target_commit}",
        "-f",
        f"request_id={request_id}",
    ]
    if component == "airflow":
        command.extend(["-f", f"confirm_real_send={str(confirm_real_send).lower()}"])
        command.extend(["-f", f"probe_target_membership={probe_target_membership or 'all'}"])
    run(command)
    run_id = discover_run(workflow, title)
    watched = run(["gh", "run", "watch", str(run_id), "--exit-status"], check=False)
    logs = run(["gh", "run", "view", str(run_id), "--log"], check=False)
    if logs.stdout:
        print(logs.stdout.rstrip())
    if watched.returncode:
        raise OpsError(f"GitHub production workflow failed: run {run_id}")
    if component == "sender" and operation == "ui_screenshot":
        artifact_name = f"wechat-sender-ui-{request_id}"
        destination = REPO_ROOT / ".local" / "diagnostics" / request_id
        run(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--name",
                artifact_name,
                "--dir",
                str(destination),
            ]
        )
        screenshot_path = destination / "wechat-ui.png"
        if not screenshot_path.is_file():
            raise OpsError("GitHub did not download the sender UI screenshot")
        print(f"artifact_path={screenshot_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run protected production operations on GitHub.")
    parser.add_argument("component", choices=tuple(WORKFLOWS))
    parser.add_argument("operation")
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-real-send", action="store_true")
    parser.add_argument("--target-membership", default="")
    args = parser.parse_args()

    target_commit = run(
        ["git", "rev-parse", "--verify", f"{args.target_commit}^{{commit}}"]
    ).stdout.strip()
    operation = args.operation
    if args.component in {"airflow", "webapp"} and operation == "deploy":
        operation = "deploy_apply" if args.apply else "deploy_preflight"
    if args.component == "sender" and operation == "deploy":
        operation = "apply" if args.apply else "dry_run"
    allowed = {
        "airflow": {
            "health",
            "deploy_preflight",
            "deploy_apply",
            "deploy_recovery",
            "db_cleanup_check",
            "phone_diagnose",
            "wechat_delivery_diagnose",
            "wechat_delivery_probe",
            "wechat_quiesce",
            "airflow_resume",
            "nswtt_config_sync",
            "pi_device_ssh_sync",
        },
        "sender": {
            "health",
            "device_diagnose",
            "ui_screenshot",
            "device_recover",
            "dry_run",
            "apply",
        },
        "webapp": {"health", "deploy_preflight", "deploy_apply"},
    }
    if operation not in allowed[args.component]:
        raise OpsError(f"unsupported {args.component} operation: {operation}")
    if operation == "wechat_delivery_probe" and not args.confirm_real_send:
        raise OpsError("real WeChat delivery requires --confirm-real-send")
    if args.confirm_real_send and operation != "wechat_delivery_probe":
        raise OpsError("--confirm-real-send is only valid for wechat_delivery_probe")
    if args.target_membership and operation != "wechat_delivery_probe":
        raise OpsError("--target-membership is only valid for wechat_delivery_probe")
    dispatch(
        args.component,
        operation,
        target_commit,
        confirm_real_send=args.confirm_real_send,
        probe_target_membership=args.target_membership,
    )


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"github-production: {exc}")
        raise SystemExit(1) from exc
