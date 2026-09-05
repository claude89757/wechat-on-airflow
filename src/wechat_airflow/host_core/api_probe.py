"""Operator-only production API transaction probe; no persistent test users/sends.

Runs in a separate CLI process, never in the serving API. All application writes
use one outer transaction that is ALWAYS rolled back. Receipt verification,
subscription create/dedupe/cancel, coffee and admin authorization use the actual
application functions. Public HTTP routing and natural delivery are separately
required by the release acceptance gate.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import text
from starlette.requests import Request

from . import api, service
from .database import get_engine
from .domain import utc_now


def run_probe() -> dict[str, Any]:
    key = uuid.uuid4().hex
    email = f"host-acceptance-{key}@acceptance.invalid"
    code = "135790"
    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 0)}
    )
    checks: dict[str, bool] = {}
    with get_engine().connect() as connection:
        outer = connection.begin()

        @contextmanager
        def probe_transaction(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
            yield connection

        try:
            with (
                patch.object(api, "transaction", probe_transaction),
                patch.object(service, "transaction", probe_transaction),
                patch.object(api, "random_verification_code", return_value=code),
            ):
                challenge = api.send_verification_code(request, {"email": email})
                checks["verificationQueued"] = (
                    connection.execute(
                        text(
                            "SELECT count(*) FROM zacks.system_email_outbox WHERE email=:email AND email_type='verification' AND expires_at>now()"
                        ),
                        {"email": email},
                    ).scalar_one()
                    == 1
                )
                try:
                    api.verify_email({"challengeId": challenge["challengeId"], "code": "000000"})
                except HTTPException as exc:
                    checks["wrongCodeRejected"] = exc.status_code == 400
                checks["wrongCodeCounted"] = (
                    connection.execute(
                        text("SELECT attempts FROM zacks.verification_challenges WHERE id=:id"),
                        {"id": challenge["challengeId"]},
                    ).scalar_one()
                    == 1
                )
                identity = api.verify_email({"challengeId": challenge["challengeId"], "code": code})
                checks["emailVerified"] = identity["email"] == email
                request = Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "path": "/",
                        "headers": [(b"authorization", f"Bearer {identity['token']}".encode())],
                        "client": ("127.0.0.1", 0),
                    }
                )
                payload = {
                    "venueIds": ["tops"],
                    "startTime": "18:00",
                    "endTime": "19:00",
                    "weekdays": [1, 2, 3, 4, 5, 6, 7],
                    "termCode": "7d",
                }
                created = api.create_subscription(request, payload)
                value = json.loads(bytes(created.body))
                checks["subscriptionCreated"] = (
                    created.status_code == 201 and value["active"] is True
                )
                try:
                    api.create_subscription(request, payload)
                except HTTPException as exc:
                    checks["duplicateRejected"] = exc.status_code == 409
                listed = api.bootstrap(request)
                checks["subscriptionListed"] = any(
                    v["id"] == value["id"] for v in listed["subscriptions"]
                )
                checks["subscriptionCancelled"] = (
                    api.cancel_subscription(value["id"], request)["success"] is True
                )
                checks["cancelPersistedInTransaction"] = (
                    connection.execute(
                        text("SELECT active FROM zacks.subscriptions WHERE id=:id"),
                        {"id": value["id"]},
                    ).scalar_one()
                    is False
                )
                checks["recreateAfterCancel"] = (
                    api.create_subscription(request, payload).status_code == 201
                )
                session = api.coffee_session(request)
                try:
                    api.coffee_invite(request, {"claimToken": session["claimToken"]})
                except HTTPException as exc:
                    checks["coffeeDelayEnforced"] = exc.status_code == 425
                try:
                    api._require_admin(request)
                except HTTPException as exc:
                    checks["nonAdminDenied"] = exc.status_code == 403
        finally:
            outer.rollback()
        with connection.begin():
            count = connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM zacks.subscriptions WHERE email=:email) + "
                    "(SELECT count(*) FROM zacks.system_email_outbox WHERE email=:email) + "
                    "(SELECT count(*) FROM zacks.verified_receipts WHERE email=:email)"
                ),
                {"email": email},
            ).scalar_one()
            checks["testWritesRolledBack"] = count == 0
    required = {
        "verificationQueued",
        "wrongCodeRejected",
        "wrongCodeCounted",
        "emailVerified",
        "subscriptionCreated",
        "duplicateRejected",
        "subscriptionListed",
        "subscriptionCancelled",
        "cancelPersistedInTransaction",
        "recreateAfterCancel",
        "coffeeDelayEnforced",
        "nonAdminDenied",
        "testWritesRolledBack",
    }
    return {
        "complete": set(checks) == required,
        "ok": set(checks) == required and all(checks.values()),
        "mode": "production_transaction_rollback",
        "publicHttpProbe": False,
        "externalTestSends": 0,
        "deploymentCommit": os.environ.get("DEPLOYMENT_COMMIT"),
        "checkedAt": utc_now().isoformat(),
        "checks": checks,
    }


def main() -> None:
    try:
        report = run_probe()
    except Exception as exc:
        report = {"complete": False, "ok": False, "errorType": type(exc).__name__}
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
