#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ALLOWED_SECRETS = {
    "airflow_fernet_key",
    "airflow_api_secret_key",
    "airflow_jwt_secret",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(ALLOWED_SECRETS))
    args = parser.parse_args()
    value = Path("/run/secrets", args.name).read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit("runtime secret is empty")
    sys.stdout.write(value)


if __name__ == "__main__":
    main()
