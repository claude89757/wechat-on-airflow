#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections.abc import Mapping

ALLOWED = {
    "TENCENT_SECRET_ID",
    "TENCENT_SECRET_KEY",
    "TENCENT_REGION",
    "EMAIL_FROM_ADDRESS",
    "EMAIL_REPLY_TO",
    "EMAIL_TEMPLATE_ID",
    "NOTIFICATION_DAILY_SEND_LIMIT",
    "STANDARD_DAILY_EMAIL_LIMIT",
    "PRIORITY_DAILY_EMAIL_LIMIT",
    "WEATHER_EMAIL_GATE_ENABLED",
    "WEATHER_EMAIL_PRECIPITATION_THRESHOLD_MM",
    "WEATHER_EMAIL_GATE_LATITUDE",
    "WEATHER_EMAIL_GATE_LONGITUDE",
    "ZACKS_CORE_DELIVERY_MODE",
}


def main() -> int:
    payload = json.load(sys.stdin)
    if not isinstance(payload, Mapping):
        raise RuntimeError("configuration payload must be an object")
    unknown = sorted(set(map(str, payload)) - ALLOWED)
    if unknown:
        raise RuntimeError(f"unsupported configuration keys: {', '.join(unknown)}")

    from airflow.sdk import Variable

    changed: list[str] = []
    for key in sorted(ALLOWED):
        if key not in payload:
            continue
        value = str(payload[key]).strip()
        if not value:
            continue
        Variable.set(key, value)
        changed.append(key)
    print(json.dumps({"success": True, "keysUpdated": changed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
