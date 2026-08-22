#!/usr/bin/env bash
set -euo pipefail

repo_path="${AIRFLOW_REPOSITORY_PATH:?AIRFLOW_REPOSITORY_PATH is required}"
ssh_target="${AIRFLOW_SSH_USER:?AIRFLOW_SSH_USER is required}@${AIRFLOW_SSH_HOST:?AIRFLOW_SSH_HOST is required}"
ssh_port="${AIRFLOW_SSH_PORT:?AIRFLOW_SSH_PORT is required}"

ssh -o BatchMode=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no \
  -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -p "$ssh_port" "$ssh_target" \
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
import urllib.error
import urllib.request
from urllib.parse import urlsplit
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
            "User-Agent": "zacks-airflow-diagnose/1",
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
    else:
        result["auth_probe_status"] = status
        result["auth_probe_ok"] = status == 400
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY

printf '%s\n' '__WEBAPP_LOGS__'
for candidate in airflow-worker worker airflow-scheduler scheduler "$service"; do
  if compose ps --services --status running | grep -qx "$candidate"; then
    compose exec -T "$candidate" sh -lc '
      find /opt/airflow/logs -type f -mmin -30 -print0 2>/dev/null \
        | xargs -0 -r grep -hF "[WEBAPP]" 2>/dev/null \
        | tail -n 120
    ' || true
  fi
done
REMOTE

printf '%s\n' '__PUBLIC_BOOTSTRAP__'
python - <<'PY'
import json
import urllib.request

url = "https://zacks.claude89757.cc/api/bootstrap"
request = urllib.request.Request(
    url,
    headers={"Accept": "application/json", "User-Agent": "zacks-production-diagnose/1"},
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
