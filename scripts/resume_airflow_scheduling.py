#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, airflow_remote, emit, run, ssh_command

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpsError("Airflow scheduling resume returned no structured result")


def remote_script() -> str:
    return r"""
set -eu
cd "$1"
dag_ids_b64="$2"

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        return 127
    fi
}

api_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$api_service"

dag_regex="$(DAG_IDS_B64="$dag_ids_b64" python3 - <<'PY'
import base64
import json
import os
import re

dag_ids = json.loads(base64.b64decode(os.environ.pop("DAG_IDS_B64")))
print("^(?:" + "|".join(re.escape(dag_id) for dag_id in dag_ids) + ")$")
PY
)"
compose exec -T "$api_service" airflow dags unpause \
    --treat-dag-id-as-regex --yes "$dag_regex" </dev/null >/dev/null

verification="$(compose exec -T -e DAG_IDS_B64="$dag_ids_b64" "$api_service" python - <<'PY'
import base64
import json
import os

from sqlalchemy import func, select
from airflow.models.dag import DagModel
from airflow.utils.session import create_session

dag_ids = json.loads(base64.b64decode(os.environ.pop("DAG_IDS_B64")))
with create_session() as session:
    found = session.scalar(
        select(func.count()).select_from(DagModel).where(DagModel.dag_id.in_(dag_ids))
    )
    paused = session.scalar(
        select(func.count())
        .select_from(DagModel)
        .where(DagModel.dag_id.in_(dag_ids), DagModel.is_paused.is_(True))
    )
print(json.dumps({"declared_dags": len(dag_ids), "found_dags": int(found or 0), "paused_dags": int(paused or 0)}))
PY
)"

service_count="$(compose ps --services --status running | wc -l | tr -d ' ')"
VERIFICATION="$verification" python3 - "$service_count" <<'PY'
import json
import os
import sys

verification = json.loads(os.environ.pop("VERIFICATION"))
service_count = int(sys.argv[1])
ok = (
    verification["found_dags"] == verification["declared_dags"]
    and verification["paused_dags"] == 0
    and service_count == 9
)
print(json.dumps({"ok": ok, "service_count": service_count, **verification}, sort_keys=True))
if not ok:
    raise SystemExit(1)
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume all declared production Airflow DAGs.")
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    target_commit = run(
        ["git", "rev-parse", "--verify", f"{args.target_commit}^{{commit}}"]
    ).stdout.strip()
    if not COMMIT_PATTERN.fullmatch(target_commit):
        raise OpsError("target revision did not resolve to a full commit")
    run(["git", "fetch", "--quiet", "origin", "main"])
    if run(
        ["git", "merge-base", "--is-ancestor", target_commit, "origin/main"], check=False
    ).returncode:
        raise OpsError("target commit is not on origin/main")

    manifest = yaml.safe_load((REPO_ROOT / "config/active-components.yaml").read_text())
    dag_ids = [str(item["dag_id"]) for item in manifest["active_dags"]]
    dag_ids_b64 = base64.b64encode(json.dumps(dag_ids, ensure_ascii=False).encode("utf-8")).decode(
        "ascii"
    )
    remote = airflow_remote()
    result = run(
        [
            *ssh_command(remote),
            "bash",
            "-s",
            "--",
            remote["repository_path"],
            dag_ids_b64,
        ],
        check=False,
        input_text=remote_script(),
    )
    if result.returncode:
        raise OpsError(
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "resume failed"
        )
    payload = parse_remote_result(result.stdout)
    payload["target_commit"] = target_commit
    emit(payload, args.format)
    if payload.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"resume-airflow-scheduling: {exc}")
        raise SystemExit(1) from exc
