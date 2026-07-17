#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


class ConfigMigrationError(RuntimeError):
    pass


def load_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigMigrationError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ConfigMigrationError(f"{label} must be a JSON object")
    return value


def render_variable_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def prepare_variables(
    exported: dict[str, Any],
    contracts: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    variable_contracts = contracts.get("variables")
    if not isinstance(variable_contracts, dict):
        raise ConfigMigrationError("config contracts must contain a variables mapping")

    selected: dict[str, str] = {}
    preserved_names: list[str] = []
    reset_names: list[str] = []
    defaulted_names: list[str] = []
    missing_names: list[str] = []

    for name, raw_contract in sorted(variable_contracts.items()):
        if not isinstance(raw_contract, dict):
            raise ConfigMigrationError(f"variable contract {name} must be a mapping")

        managed = raw_contract.get("managed_by_application") is True
        policy = raw_contract.get("fresh_start_policy") if managed else "preserve"
        if policy == "reset":
            selected[name] = render_variable_value(raw_contract.get("default", []))
            reset_names.append(name)
            continue
        if policy != "preserve":
            raise ConfigMigrationError(f"variable contract {name} has invalid fresh_start_policy")

        if name in exported:
            selected[name] = render_variable_value(exported[name])
            preserved_names.append(name)
        elif "default" in raw_contract:
            selected[name] = render_variable_value(raw_contract["default"])
            defaulted_names.append(name)
        else:
            missing_names.append(name)

    ignored_names = sorted(set(exported) - set(variable_contracts))
    report = {
        "ok": not missing_names,
        "selected_count": len(selected),
        "preserved_names": preserved_names,
        "reset_names": reset_names,
        "defaulted_names": defaulted_names,
        "missing_names": missing_names,
        "ignored_count": len(ignored_names),
    }
    return selected, report


def write_private_json(path: Path, payload: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare an Airflow Variable import for a fresh metadata database."
    )
    parser.add_argument("exported_variables", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--contracts",
        type=Path,
        default=Path("/opt/airflow/project/config/config-contracts.yaml"),
    )
    args = parser.parse_args()

    exported = load_mapping(args.exported_variables, "Airflow Variable export")
    try:
        contracts = yaml.safe_load(args.contracts.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigMigrationError(f"cannot read config contracts: {args.contracts}") from exc
    if not isinstance(contracts, dict):
        raise ConfigMigrationError("config contracts must be a mapping")

    prepared, report = prepare_variables(exported, contracts)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(1)
    write_private_json(args.output, prepared)


if __name__ == "__main__":
    try:
        main()
    except ConfigMigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
