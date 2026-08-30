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
compose_with_timeout() {
  local timeout_seconds="$1"
  shift
  if docker compose version >/dev/null 2>&1; then
    timeout "$timeout_seconds" docker compose "$@"
  else
    timeout "$timeout_seconds" docker-compose "$@"
  fi
}
service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
airflow_python() {
  compose exec -T "$service" sh -c '
    if [ -x /opt/bitnami/airflow/venv/bin/python ]; then
      exec /opt/bitnami/airflow/venv/bin/python "$@"
    fi
    exec python "$@"
  ' sh "$@"
}
airflow_python - <<'PY'
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from airflow.models.variable import Variable

url = str(Variable.get("WEBAPP_OBSERVATION_API_URL", default_var="") or "").strip()
token = str(Variable.get("WEBAPP_OBSERVATION_API_TOKEN", default_var="") or "").strip()
parsed = urlsplit(url) if url else None
result = {
    "url_configured": bool(url),
    "token_configured": bool(token),
    "url_scheme": parsed.scheme if parsed else "",
    "url_host": parsed.netloc if parsed else "",
    "url_path": parsed.path if parsed else "",
}
if url and token:
    request = urllib.request.Request(
        url,
        data=b"{",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "zacks-airflow-diagnose/5",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:
        result["probe_error_type"] = type(exc).__name__
        result["probe_error"] = str(exc)[:200]
    if "status" in locals():
        result["auth_probe_status"] = status
        result["auth_probe_ok"] = status == 400

    reconcile_url = urlunsplit((parsed.scheme, parsed.netloc, "/api/internal/reconcile-deliveries", "", ""))
    aggregate = {
        "iterations": 0,
        "notifications": {
            "selected": 0,
            "claimed": 0,
            "checked": 0,
            "delivered": 0,
            "failed": 0,
            "pending": 0,
            "unavailable": 0,
            "errors": {},
        },
        "systemEmails": {
            "selected": 0,
            "claimed": 0,
            "checked": 0,
            "delivered": 0,
            "failed": 0,
            "pending": 0,
            "unavailable": 0,
            "errors": {},
        },
    }
    reconcile_ok = True
    last_status = None
    for iteration in range(10):
        reconcile_request = urllib.request.Request(
            reconcile_url,
            data=b"{}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "zacks-airflow-diagnose/5",
            },
            method="POST",
        )
        payload = {}
        try:
            with urllib.request.urlopen(reconcile_request, timeout=60) as response:
                last_status = response.getcode()
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {"success": False, "errorCode": f"HTTP_{exc.code}"}
        except Exception as exc:
            last_status = None
            payload = {
                "success": False,
                "errorCode": type(exc).__name__,
            }

        aggregate["iterations"] += 1
        for queue in ("notifications", "systemEmails"):
            section = payload.get(queue) if isinstance(payload, dict) else None
            if not isinstance(section, dict):
                continue
            for key in ("selected", "claimed", "checked", "delivered", "failed", "pending", "unavailable"):
                aggregate[queue][key] += int(section.get(key) or 0)
            errors = section.get("errors") or {}
            if isinstance(errors, dict):
                for code, count in errors.items():
                    aggregate[queue]["errors"][str(code)] = (
                        aggregate[queue]["errors"].get(str(code), 0) + int(count or 0)
                    )

        if last_status != 200 or not bool(payload.get("success", False)):
            reconcile_ok = False
            result["reconcile_error_code"] = str(payload.get("errorCode") or "provider_status_unavailable")
            break

        selected = int((payload.get("notifications") or {}).get("selected") or 0)
        selected += int((payload.get("systemEmails") or {}).get("selected") or 0)
        if selected == 0:
            break
        time.sleep(0.5)

    result["reconcile_status"] = last_status
    result["reconcile_ok"] = reconcile_ok
    result["reconcile_summary"] = aggregate

print(json.dumps(result, ensure_ascii=False, sort_keys=True))
if result.get("reconcile_ok") is False:
    raise SystemExit(2)
PY
printf '%s\n' '__WEBAPP_LOGS__'
for candidate in airflow-worker worker; do
  if compose ps --services --status running | grep -qx "$candidate"; then
    compose_with_timeout 12s exec -T "$candidate" sh -lc '
      find /opt/airflow/logs -type f -path "*dsh_ydmap_watcher*" -mmin -180 -size -5M -print0 2>/dev/null \
        | xargs -0 -r grep -hE "\[WEBAPP\]|Error checking 大沙河国际网球中心|start to check 大沙河国际网球中心" 2>/dev/null \
        | tail -n 240
    ' || true
  fi
done
REMOTE

printf '%s\n' '__PUBLIC_BOOTSTRAP__'
python - <<'PY'
import json
import urllib.request

request = urllib.request.Request(
    "https://zacks.claude89757.cc/api/bootstrap",
    headers={"Accept": "application/json", "User-Agent": "zacks-production-diagnose/5"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))
print(json.dumps({
    "metrics": payload.get("metrics", {}),
    "venues": [
        {
            "id": venue.get("id"),
            "healthy": venue.get("healthy"),
            "lastInspectionAt": venue.get("lastInspectionAt"),
        }
        for venue in payload.get("venues", [])
        if isinstance(venue, dict)
    ],
}, ensure_ascii=False, sort_keys=True))
PY
