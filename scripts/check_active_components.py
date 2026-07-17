#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "active-components.yaml"
CONTRACTS = ROOT / "config" / "config-contracts.yaml"


def fail(message: str) -> None:
    print(f"active-components: {message}", file=sys.stderr)
    raise SystemExit(1)


def string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def module_path(module_name: str) -> Path:
    return ROOT / "src" / Path(*module_name.split(".")).with_suffix(".py")


def main() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    contracts = yaml.safe_load(CONTRACTS.read_text(encoding="utf-8"))
    active_dags = manifest.get("active_dags")
    if not isinstance(active_dags, list) or not active_dags:
        fail("active_dags must be a non-empty list")

    contract_names = set((contracts.get("variables") or {}).keys())
    dag_ids: set[str] = set()
    files: set[str] = set()
    undeclared_variables: set[str] = set()
    declared_modules: set[str] = set()

    for component in active_dags:
        dag_id = component.get("dag_id")
        relative_file = component.get("file")
        if not dag_id or not relative_file:
            fail("every active DAG requires dag_id and file")
        if dag_id in dag_ids:
            fail(f"duplicate dag_id: {dag_id}")
        if relative_file in files:
            fail(f"duplicate DAG file: {relative_file}")
        dag_ids.add(dag_id)
        files.add(relative_file)

        path = ROOT / relative_file
        if not path.is_file():
            fail(f"missing DAG file: {relative_file}")
        if not path.is_relative_to(ROOT / "dags"):
            fail(f"DAG file is outside dags/: {relative_file}")
        if dag_id not in string_literals(path):
            fail(f"{relative_file} does not contain its declared dag_id {dag_id!r}")

        variables = component.get("variables") or []
        if not isinstance(variables, list):
            fail(f"{dag_id} variables must be a list")
        undeclared_variables.update(set(variables) - contract_names)

        verification = component.get("verification") or []
        if not verification:
            fail(f"{dag_id} has no verification contract")
        declared_modules.update(component.get("direct_modules") or [])

    dag_files = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "dags").rglob("*.py")
        if "__pycache__" not in path.parts
    }
    if dag_files != files:
        fail(
            "dags/ must contain exactly the active DAG files; "
            f"undeclared={sorted(dag_files - files)}, missing={sorted(files - dag_files)}"
        )

    for contract in (manifest.get("shared_contracts") or {}).values():
        declared_modules.update(contract.get("modules") or [])
    missing_modules = sorted(
        module for module in declared_modules if not module_path(module).is_file()
    )
    if missing_modules:
        fail("declared source modules are missing: " + ", ".join(missing_modules))

    active_services = manifest.get("active_services") or []
    for service in active_services:
        service_id = service.get("service_id")
        service_files = service.get("files") or []
        if not service_id or not service_files:
            fail("every active service requires service_id and files")
        for relative_file in service_files:
            if not (ROOT / relative_file).is_file():
                fail(f"active service {service_id} is missing file: {relative_file}")
        if not service.get("verification"):
            fail(f"active service {service_id} has no verification contract")

    if undeclared_variables:
        fail(
            "variables missing from config/config-contracts.yaml: "
            + ", ".join(sorted(undeclared_variables))
        )

    print(
        "active-components: ok "
        f"dags={len(dag_ids)} services={len(active_services)} "
        f"declared_variables={len(contract_names)}"
    )


if __name__ == "__main__":
    main()
