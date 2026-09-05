"""Read-only, privacy-safe checkpoint for resuming an interrupted first cutover."""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from sqlalchemy import text

from .database import get_engine
from .migration import EXPORT_TABLES


def migration_reconciled(details: Any) -> bool:
    if not isinstance(details, dict):
        return False
    proof = details.get("reconciliation")
    if not isinstance(proof, dict) or proof.get("providerIdentityPreserved") is not True:
        return False
    for table in EXPORT_TABLES:
        entry = proof.get(table)
        if not isinstance(entry, dict):
            return False
        count = entry.get("sourceCount")
        matched = entry.get("matchedCount")
        if type(count) is not int or type(matched) is not int or count < 0 or count != matched:
            return False
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("keysSha256", ""))):
            return False
    return True


def read_checkpoint(expected_commit: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise RuntimeError("an exact commit is required")
    if os.environ.get("DEPLOYMENT_COMMIT") != expected_commit:
        raise RuntimeError("checkpoint container commit mismatch")
    # prepare-runtime has already migrated the schema. This diagnostic itself
    # performs ONLY SELECTs, without ensure_schema or any business writes.
    with get_engine().connect() as connection:
        state = connection.execute(
            text("SELECT activated_at, delivery_enabled, wechat_enabled FROM zacks.runtime_control WHERE singleton")
        ).mappings().one()
        migration = connection.execute(
            text("SELECT source_revision, imported_at, details FROM zacks.migration_state WHERE source='cloudflare-d1'")
        ).mappings().first()
    complete = bool(
        migration and migration["imported_at"] and migration_reconciled(migration["details"])
    )
    if state["activated_at"] is not None and not complete:
        raise RuntimeError("activated Host Core has no verified migration checkpoint")
    return {
        "deploymentCommit": expected_commit,
        "migrationComplete": complete,
        "everActivated": state["activated_at"] is not None,
        "deliveryEnabled": state["delivery_enabled"],
        "wechatEnabled": state["wechat_enabled"],
        "sourceRevision": migration["source_revision"] if complete and migration else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(read_checkpoint(args.expected_commit), sort_keys=True))


if __name__ == "__main__":
    main()
