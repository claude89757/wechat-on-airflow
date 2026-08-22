#!/usr/bin/env bash
set -euo pipefail

repo_path="${AIRFLOW_REPOSITORY_PATH:?AIRFLOW_REPOSITORY_PATH is required}"
ssh_target="${AIRFLOW_SSH_USER:?AIRFLOW_SSH_USER is required}@${AIRFLOW_SSH_HOST:?AIRFLOW_SSH_HOST is required}"
ssh_port="${AIRFLOW_SSH_PORT:?AIRFLOW_SSH_PORT is required}"
output_path=".local/diagnostics/priority-invite.json"

mkdir -p "$(dirname "$output_path")"
umask 077

ssh -o BatchMode=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no \
  -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o ServerAliveInterval=10 \
  -o ServerAliveCountMax=3 -p "$ssh_port" "$ssh_target" \
  bash -s -- "$repo_path" > "$output_path" <<'REMOTE'
set -euo pipefail
cd "$1"
compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}
service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$service"
compose exec -T "$service" python - <<'PY'
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from airflow.models.variable import Variable

observation_url = str(
    Variable.get("WEBAPP_OBSERVATION_API_URL", default_var="") or ""
).strip()
token = str(
    Variable.get("WEBAPP_OBSERVATION_API_TOKEN", default_var="") or ""
).strip()
if not observation_url or not token:
    raise SystemExit("Web observation configuration is incomplete")
parts = urlsplit(observation_url)
endpoint = urlunsplit(
    (parts.scheme, parts.netloc, "/api/internal/priority-invites", "", "")
)
payload = json.dumps(
    {
        "count": 1,
        "expiresInDays": 90,
        "note": "Issued through owner-only production ChatOps",
    }
).encode("utf-8")
request = urllib.request.Request(
    endpoint,
    data=payload,
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "zacks-priority-invite-chatops/1",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    detail = exc.read(256).decode("utf-8", errors="replace")
    raise SystemExit(f"Invite creation failed with HTTP {exc.code}: {detail}") from exc
codes = result.get("codes") if isinstance(result, dict) else None
if not isinstance(codes, list) or len(codes) != 1 or not isinstance(codes[0], str):
    raise SystemExit("Invite creation returned an invalid response")
print(
    json.dumps(
        {"code": codes[0], "expiresAt": result.get("expiresAt")},
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
REMOTE

python - "$output_path" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
code = payload.get("code")
if not isinstance(code, str) or not re.fullmatch(r"ACE-[A-Z]+-[A-Z]+-[A-Z0-9]+", code):
    raise SystemExit("Generated invite artifact is invalid")
print(f"::add-mask::{code}")
print("Priority invite created and stored in a protected one-day artifact.")
PY
