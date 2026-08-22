#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

from _ops import OpsError, airflow_remote, emit, run, ssh_command


def _extract_json_line(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpsError("production probe did not return JSON")


def _public_bootstrap(api_url: str) -> dict[str, Any]:
    if not api_url:
        return {"ok": False, "error": "observation URL is not configured"}
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(api_url)
    bootstrap_url = urlunsplit((parts.scheme, parts.netloc, "/api/bootstrap", "", ""))
    request = urllib.request.Request(
        bootstrap_url,
        headers={"Accept": "application/json", "User-Agent": "zacks-production-diagnose/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:200]}

    venues = payload.get("venues") if isinstance(payload, dict) else None
    if not isinstance(venues, list):
        return {"ok": False, "error": "bootstrap venues missing"}
    return {
        "ok": True,
        "metrics": payload.get("metrics", {}),
        "venues": [
            {
                "id": item.get("id"),
                "healthy": item.get("healthy"),
                "lastInspectionAt": item.get("lastInspectionAt"),
            }
            for item in venues
            if isinstance(item, dict)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only diagnosis for Airflow -> Web observation publishing."
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    remote = airflow_remote()
    script = r'''set -eu
cd "$1"
compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    return 127
  fi
}
service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$service"
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
    "api_url": url,
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
            body = response.read(256).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read(256).decode("utf-8", errors="replace")
    except Exception as exc:
        result["probe_error_type"] = type(exc).__name__
        result["probe_error"] = str(exc)[:200]
    else:
        result["auth_probe_status"] = status
        result["auth_probe_ok"] = status == 400
        result["auth_probe_response"] = body[:200]
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY
printf '__WEBAPP_LOGS__\n'
for candidate in airflow-worker worker airflow-scheduler scheduler "$service"; do
  if compose ps --services --status running | grep -qx "$candidate"; then
    compose exec -T "$candidate" sh -lc '
      find /opt/airflow/logs -type f -mmin -30 -print0 2>/dev/null \
        | xargs -0 -r grep -hF "[WEBAPP]" 2>/dev/null \
        | tail -n 120
    ' || true
  fi
done
'''

    result = run(
        ssh_command(remote) + ["bash", "-s", "--", remote["repository_path"]],
        input_text=script,
    )
    remote_probe = _extract_json_line(result.stdout)
    log_text = result.stdout.split("__WEBAPP_LOGS__\n", 1)[1] if "__WEBAPP_LOGS__\n" in result.stdout else ""
    log_lines = [line.strip() for line in log_text.splitlines() if "[WEBAPP]" in line]
    published = [line for line in log_lines if "observation published" in line]
    failed = [line for line in log_lines if "observation publishing failed" in line]
    skipped = [line for line in log_lines if "observation publishing skipped" in line]

    public = _public_bootstrap(str(remote_probe.get("api_url") or ""))
    remote_probe.pop("api_url", None)
    payload = {
        "ok": bool(remote_probe.get("auth_probe_ok")) and bool(public.get("ok")),
        "airflow_to_web": remote_probe,
        "recent_webapp_log_counts": {
            "published": len(published),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "recent_webapp_log_tail": log_lines[-40:],
        "public_bootstrap": public,
    }
    emit(payload, args.format)


if __name__ == "__main__":
    main()
