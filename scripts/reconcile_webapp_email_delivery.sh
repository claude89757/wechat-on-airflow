#!/usr/bin/env bash
set -euo pipefail

repo_path="${AIRFLOW_REPOSITORY_PATH:?AIRFLOW_REPOSITORY_PATH is required}"
ssh_target="${AIRFLOW_SSH_USER:?AIRFLOW_SSH_USER is required}@${AIRFLOW_SSH_HOST:?AIRFLOW_SSH_HOST is required}"
ssh_port="${AIRFLOW_SSH_PORT:?AIRFLOW_SSH_PORT is required}"

ssh -o BatchMode=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no \
  -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o ServerAliveInterval=10 \
  -o ServerAliveCountMax=3 -p "$ssh_port" "$ssh_target" \
  bash -s -- "$repo_path" <<'REMOTE'
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
compose exec -T "$service" sh -c '
  if [ -x /opt/bitnami/airflow/venv/bin/python ]; then
    exec /opt/bitnami/airflow/venv/bin/python "$@"
  fi
  exec python "$@"
' sh - <<'PY'
import json
import time
import urllib.error
import urllib.request
from airflow.models.variable import Variable

observation_url = str(Variable.get("WEBAPP_OBSERVATION_API_URL", default_var="") or "").strip()
token = str(Variable.get("WEBAPP_OBSERVATION_API_TOKEN", default_var="") or "").strip()
if not observation_url or not token:
    raise SystemExit("webapp observation URL/token is not configured")
marker = "/api/internal/observations"
if marker not in observation_url:
    raise SystemExit("WEBAPP_OBSERVATION_API_URL has an unexpected path")
endpoint = observation_url.split(marker, 1)[0] + "/api/internal/delivery-reconcile"

aggregate = {
    "iterations": 0,
    "notification_selected": 0,
    "notification_leased": 0,
    "notification_checked": 0,
    "notification_delivered": 0,
    "notification_failed": 0,
    "notification_pending": 0,
    "notification_unavailable": 0,
    "system_selected": 0,
    "system_leased": 0,
    "system_checked": 0,
    "system_delivered": 0,
    "system_failed": 0,
    "system_pending": 0,
    "system_unavailable": 0,
    "error_codes": {},
}

for iteration in range(10):
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"limit": 20}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "zacks-delivery-reconcile/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"delivery reconciliation HTTP {exc.code}: {detail}") from exc

    aggregate["iterations"] += 1
    for prefix, section_name in (("notification", "notifications"), ("system", "systemEmails")):
        section = payload.get(section_name) or {}
        for key in ("selected", "leased", "checked", "delivered", "failed", "pending", "unavailable"):
            aggregate[f"{prefix}_{key}"] += int(section.get(key) or 0)
        for code, count in (section.get("errors") or {}).items():
            aggregate["error_codes"][code] = aggregate["error_codes"].get(code, 0) + int(count or 0)

    print(json.dumps({"iteration": iteration + 1, **payload}, ensure_ascii=False, sort_keys=True))
    selected = int((payload.get("notifications") or {}).get("selected") or 0)
    selected += int((payload.get("systemEmails") or {}).get("selected") or 0)
    if selected == 0:
        break
    time.sleep(0.5)

print(json.dumps({"aggregate": aggregate}, ensure_ascii=False, sort_keys=True))
PY
REMOTE
