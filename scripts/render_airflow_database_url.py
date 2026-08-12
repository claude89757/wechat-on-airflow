#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-backend", action="store_true")
    args = parser.parse_args()

    username = quote(os.environ.get("AIRFLOW_DATABASE_USERNAME", "airflow"), safe="")
    database = quote(os.environ.get("AIRFLOW_DATABASE_NAME", "airflow"), safe="")
    password = quote(
        Path("/run/secrets/airflow_database_password").read_text(encoding="utf-8").strip(),
        safe="",
    )
    prefix = "db+postgresql" if args.result_backend else "postgresql+psycopg2"
    sys.stdout.write(f"{prefix}://{username}:{password}@postgresql:5432/{database}")


if __name__ == "__main__":
    main()
