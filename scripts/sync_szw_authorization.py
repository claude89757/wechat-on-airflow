#!/usr/bin/env python3
"""Rotate the CRLand account pool through the protected production workflow."""

from __future__ import annotations

import base64
import binascii
import inspect
import json
import math
import os
import re
import shlex
import subprocess
import time

from _ops import REPO_ROOT, OpsError, airflow_remote, emit, ssh_command

VARIABLE_NAME = "SZW_API_AUTHORIZATIONS"
LEGACY_VARIABLE_NAME = "SZW_API_AUTHORIZATION"
ACCOUNT_COUNT = 3
MAX_AUTHORIZATION_LENGTH = 8192
MAX_POOL_LENGTH = ACCOUNT_COUNT * (MAX_AUTHORIZATION_LENGTH + 4) + 2
SYNC_TIMEOUT_SECONDS = 240
SUCCESS_RESULT = {
    "ok": True,
    "variable": VARIABLE_NAME,
    "accounts_verified": 3,
    "areas_verified": 9,
    "legacy_updated": True,
    "stored_matches": True,
}
REMOTE_ERRORS = {
    "authorization_validation_failed",
    "szw_outdoor_probe_failed",
    "szw_covered_probe_failed",
    "gba_probe_failed",
    "variable_write_failed",
}


def validated_authorization(raw: str, *, now: float | None = None) -> str:
    """Validate structure/expiry only; the upstream probes establish acceptance."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_AUTHORIZATION_LENGTH:
        raise OpsError("SZW_API_AUTHORIZATION is missing or exceeds the size limit")
    if "\n" in raw or "\r" in raw:
        raise OpsError("SZW_API_AUTHORIZATION must contain a valid Wechat JWT")
    authorization = raw.strip()
    token = authorization.removeprefix("Wechat ")
    parts = token.split(".")
    if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
        raise OpsError("SZW_API_AUTHORIZATION must contain a valid Wechat JWT")
    try:
        decoded = [
            base64.b64decode(part + "=" * (-len(part) % 4), altchars=b"-_", validate=True)
            for part in parts
        ]
        header = json.loads(decoded[0].decode("utf-8"))
        payload = json.loads(decoded[1].decode("utf-8"))
        if not isinstance(header, dict) or not isinstance(payload, dict):
            raise ValueError
        if header.get("alg") != "HS256":
            raise ValueError
        expires_at = payload["exp"]
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, int | float)
            or not math.isfinite(expires_at)
            or len(decoded[2]) != 32
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError, binascii.Error):
        raise OpsError("SZW_API_AUTHORIZATION contains a malformed JWT") from None
    if expires_at <= (time.time() if now is None else now):
        raise OpsError("SZW_API_AUTHORIZATION has expired")
    return f"Wechat {token}"


def validated_pool(raw: str, *, now: float | None = None) -> str:
    """Require three distinct account identities without exposing any claim."""
    if not raw or len(raw) > MAX_POOL_LENGTH:
        raise OpsError("SZW_API_AUTHORIZATIONS is missing or exceeds the size limit")
    try:
        candidates = json.loads(raw)
    except (TypeError, ValueError):
        raise OpsError("SZW_API_AUTHORIZATIONS must be a JSON list of three JWTs") from None
    if (
        not isinstance(candidates, list)
        or len(candidates) != ACCOUNT_COUNT
        or any(not isinstance(candidate, str) for candidate in candidates)
    ):
        raise OpsError("SZW_API_AUTHORIZATIONS must be a JSON list of three JWTs")
    current_time = time.time() if now is None else now
    canonical = [validated_authorization(candidate, now=current_time) for candidate in candidates]
    account_claims: set[str] = set()
    for authorization in canonical:
        segment = authorization.removeprefix("Wechat ").split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8")
        )
        identities = {
            claims[field].strip()
            for field in ("openid", "sub")
            if isinstance(claims.get(field), str) and claims[field].strip()
        }
        if not identities:
            raise OpsError("SZW_API_AUTHORIZATIONS requires an account identity in every JWT")
        if account_claims & identities:
            raise OpsError("SZW_API_AUTHORIZATIONS must contain three distinct accounts")
        account_claims.update(identities)
    return json.dumps(canonical, ensure_ascii=True, separators=(",", ":"))


# This payload contains code only. The candidate credential is read from SSH stdin,
# never placed in the remote command, a temporary file, or the container environment.
REMOTE_PYTHON = r"""
import base64
import binascii
import contextlib
import datetime
import hmac
import json
import logging
import math
import os
import re
import sys
import time
from zoneinfo import ZoneInfo

OpsError = ValueError
ACCOUNT_COUNT = 3
MAX_AUTHORIZATION_LENGTH = 8192
MAX_POOL_LENGTH = ACCOUNT_COUNT * (MAX_AUTHORIZATION_LENGTH + 4) + 2
__VALIDATION_CODE__

logging.disable(logging.CRITICAL)
stage = "authorization_validation_failed"
account_index = 0
result = {"ok": False, "variable": "SZW_API_AUTHORIZATIONS", "error": stage}
try:
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        from airflow.models.variable import Variable
        from airflow.utils.session import create_session
        from wechat_airflow.venues.szw_watcher import (
            CRLAND_VENUES,
            SZW_APP_ID,
            SZW_HOST,
            SZW_MATRIX_API_URL,
            create_crland_http_session,
        )

        raw = sys.stdin.read(MAX_POOL_LENGTH + 1)
        if len(raw) > MAX_POOL_LENGTH:
            raise ValueError
        normalized = validated_pool(raw)
        authorizations = json.loads(normalized)
        reserve_date = (
            datetime.datetime.now(ZoneInfo("Asia/Shanghai")) + datetime.timedelta(days=1)
        ).date().isoformat()
        areas = (
            ("szw_outdoor_probe_failed", CRLAND_VENUES["szw"].booking_areas[0]),
            ("szw_covered_probe_failed", CRLAND_VENUES["szw"].booking_areas[1]),
            ("gba_probe_failed", CRLAND_VENUES["gba"].booking_areas[0]),
        )
        with create_crland_http_session() as client:
            client.trust_env = False
            for account_index, authorization in enumerate(authorizations, start=1):
                client.cookies.clear()
                for index, (stage, area) in enumerate(areas):
                    if index or account_index > 1:
                        time.sleep(2)
                    response = client.post(
                        SZW_MATRIX_API_URL,
                        headers={
                            "Host": SZW_HOST,
                            "appId": SZW_APP_ID,
                            "Authorization": authorization,
                            "projectUuid": area.project_uuid,
                            "Content-Type": "application/json",
                            "xweb_xhr": "1",
                            "Referer": f"https://servicewechat.com/{SZW_APP_ID}/69/page-frame.html",
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 "
                            "Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
                            "NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF "
                            "MacWechat/3.8.7(0x13080712) UnifiedPCMacWechat(0xf2641d55) XWEB/25561",
                            "Accept": "*/*",
                            "Sec-Fetch-Site": "cross-site",
                            "Sec-Fetch-Mode": "cors",
                            "Sec-Fetch-Dest": "empty",
                            "Accept-Language": "zh-CN,zh;q=0.9",
                        },
                        json={
                            "fieldAreaUuid": area.field_area_uuid,
                            "reserveDate": reserve_date,
                            "enterpriseUuid": "",
                            "discountSpecUuid": "",
                            "projectUuid": area.project_uuid,
                        },
                        timeout=(5, 15),
                        allow_redirects=False,
                    )
                    try:
                        if response.status_code != 200:
                            raise ValueError
                        body = response.json()
                        matrix = body.get("result") if isinstance(body, dict) else None
                        if (
                            not isinstance(body, dict)
                            or body.get("code") != 200
                            or not isinstance(matrix, dict)
                            or not isinstance(matrix.get("fieldList"), list)
                            or not isinstance(matrix.get("matrix"), list)
                        ):
                            raise ValueError
                    finally:
                        response.close()

        stage = "variable_write_failed"
        replacements = {
            "SZW_API_AUTHORIZATIONS": normalized,
            "SZW_API_AUTHORIZATION": authorizations[0],
        }
        with create_session() as session:
            for name, value in replacements.items():
                Variable.set(name, value, session=session)
            for name, value in replacements.items():
                stored = session.query(Variable).filter(Variable.key == name).one().get_val()
                if not isinstance(stored, str) or not hmac.compare_digest(stored, value):
                    raise ValueError
        result = {
            "ok": True,
            "variable": "SZW_API_AUTHORIZATIONS",
            "accounts_verified": 3,
            "areas_verified": 9,
            "legacy_updated": True,
            "stored_matches": True,
        }
except Exception:
    result = {"ok": False, "variable": "SZW_API_AUTHORIZATIONS", "error": stage, "account_index": account_index}
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result["ok"] else 1)
""".replace(
    "__VALIDATION_CODE__",
    inspect.getsource(validated_authorization) + "\n" + inspect.getsource(validated_pool),
)


def sync(pool_json: str) -> dict[str, object]:
    candidate = validated_pool(pool_json)
    remote = airflow_remote()
    remote_script = """
set -eu
cd "$1"
compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}
compose exec -T airflow-api-server python -c "$2"
"""
    remote_command = " ".join(
        [
            "bash -c",
            shlex.quote(remote_script),
            "szw-authorization-sync",
            shlex.quote(remote["repository_path"]),
            shlex.quote(REMOTE_PYTHON),
        ]
    )
    environment = dict(os.environ)
    environment.pop(VARIABLE_NAME, None)
    environment.pop(LEGACY_VARIABLE_NAME, None)
    try:
        # Do not use _ops.run: its failure text includes raw subprocess output.
        completed = subprocess.run(
            [*ssh_command(remote), remote_command],
            cwd=REPO_ROOT,
            input=candidate,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=SYNC_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise OpsError("SZW authorization sync timed out; verify the stored state") from None
    except Exception:
        raise OpsError("SZW authorization sync failed in its protected transport") from None
    try:
        response = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, TypeError, ValueError):
        response = None
    if completed.returncode == 0 and response == SUCCESS_RESULT:
        return dict(SUCCESS_RESULT)
    error = response.get("error") if isinstance(response, dict) else None
    if isinstance(error, str) and error in REMOTE_ERRORS:
        account = response.get("account_index")
        context = (
            f" (account {account})"
            if type(account) is int and 1 <= account <= ACCOUNT_COUNT
            else ""
        )
        raise OpsError(f"SZW authorization sync failed: {error}{context}")
    raise OpsError("SZW authorization sync failed; verify the stored state")


def main() -> None:
    emit(sync(os.environ.get(VARIABLE_NAME, "")), "json")


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"sync-szw-authorization: {exc}")
        raise SystemExit(1) from None
