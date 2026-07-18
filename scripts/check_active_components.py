#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "active-components.yaml"
CONTRACTS = ROOT / "config" / "config-contracts.yaml"
RUNTIME_TARGET = ROOT / "config" / "runtime-target.yaml"
AIRFLOW_DOCKERFILE = ROOT / "docker" / "airflow" / "Dockerfile"
COMPOSE_FILE = ROOT / "docker-compose.yml"
DAG_MAX_LINES = 120
FORBIDDEN_DAG_IMPORT_ROOTS = {"httpx", "paramiko", "requests", "socket", "urllib3"}


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


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def dag_schedule_contract(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    schedule_nodes = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "DAG"
        for keyword in node.keywords
        if keyword.arg == "schedule"
    ]
    if len(schedule_nodes) != 1:
        fail(f"{path.relative_to(ROOT)} must define exactly one DAG schedule")

    schedule_node = schedule_nodes[0]
    if isinstance(schedule_node, ast.Constant) and isinstance(schedule_node.value, str):
        return schedule_node.value

    if (
        isinstance(schedule_node, ast.Call)
        and isinstance(schedule_node.func, ast.Name)
        and schedule_node.func.id == "timedelta"
    ):
        units = {"days": 86_400, "hours": 3_600, "minutes": 60, "seconds": 1}
        total_seconds = 0
        for keyword in schedule_node.keywords:
            if keyword.arg not in units or not isinstance(keyword.value, ast.Constant):
                fail(f"{path.relative_to(ROOT)} has an unsupported timedelta schedule")
            if not isinstance(keyword.value.value, int):
                fail(f"{path.relative_to(ROOT)} timedelta schedule values must be integers")
            total_seconds += keyword.value.value * units[keyword.arg]
        if total_seconds <= 0:
            fail(f"{path.relative_to(ROOT)} timedelta schedule must be positive")
        if total_seconds % 3_600 == 0:
            return f"every_{total_seconds // 3_600}_hours"
        if total_seconds % 60 == 0:
            return f"every_{total_seconds // 60}_minutes"
        return f"every_{total_seconds}_seconds"

    fail(f"{path.relative_to(ROOT)} has an unsupported schedule expression")


def module_path(module_name: str) -> Path:
    return ROOT / "src" / Path(*module_name.split(".")).with_suffix(".py")


def main() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    contracts = yaml.safe_load(CONTRACTS.read_text(encoding="utf-8"))
    runtime_target = yaml.safe_load(RUNTIME_TARGET.read_text(encoding="utf-8"))
    production = manifest.get("production", {})
    if production.get("deployment_policy") != "exact_local_head" or "deployed_commit" in production:
        fail("production deployment identity must be verified dynamically against local HEAD")
    active_dags = manifest.get("active_dags")
    if not isinstance(active_dags, list) or not active_dags:
        fail("active_dags must be a non-empty list")

    variable_contracts = contracts.get("variables") or {}
    connection_contracts = contracts.get("connections") or {}
    if not isinstance(variable_contracts, dict):
        fail("config-contracts variables must be a mapping")
    if not isinstance(connection_contracts, dict):
        fail("config-contracts connections must be a mapping")

    contract_names = set(variable_contracts)
    connection_contract_names = set(connection_contracts)
    dag_ids: set[str] = set()
    files: set[str] = set()
    undeclared_variables: set[str] = set()
    undeclared_connections: set[str] = set()
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
        declared_schedule = component.get("schedule")
        actual_schedule = dag_schedule_contract(path)
        if actual_schedule != declared_schedule:
            fail(
                f"{relative_file} schedule mismatch: "
                f"manifest={declared_schedule!r}, source={actual_schedule!r}"
            )
        if len(path.read_text(encoding="utf-8").splitlines()) > DAG_MAX_LINES:
            fail(f"{relative_file} exceeds the {DAG_MAX_LINES}-line DAG wiring limit")
        forbidden_imports = sorted(
            module
            for module in imported_modules(path)
            if module.split(".", maxsplit=1)[0] in FORBIDDEN_DAG_IMPORT_ROOTS
        )
        if forbidden_imports:
            fail(
                f"{relative_file} imports network/runtime clients directly: "
                + ", ".join(forbidden_imports)
            )

        variables = component.get("variables") or []
        if not isinstance(variables, list):
            fail(f"{dag_id} variables must be a list")
        undeclared_variables.update(set(variables) - contract_names)

        if "connections" not in component:
            fail(f"{dag_id} must declare connections, using [] when none are required")
        connections = component.get("connections") or []
        if not isinstance(connections, list):
            fail(f"{dag_id} connections must be a list")
        undeclared_connections.update(set(connections) - connection_contract_names)

        tasks = component.get("tasks") or []
        if not isinstance(tasks, list) or not tasks:
            fail(f"{dag_id} tasks must be a non-empty list")
        if len(tasks) != len(set(tasks)):
            fail(f"{dag_id} contains duplicate task IDs")

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

    if runtime_target.get("target", {}).get("dag_distribution") != "image":
        fail("Airflow DAG distribution must be declared as image")
    dockerfile = AIRFLOW_DOCKERFILE.read_text(encoding="utf-8")
    if "dags /opt/airflow/dags" not in dockerfile:
        fail("Airflow image must copy dags/ into /opt/airflow/dags")
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    airflow_volumes = compose.get("x-airflow-common", {}).get("volumes", [])
    if any("/opt/airflow/dags" in str(volume) for volume in airflow_volumes):
        fail("Airflow services must use image-bundled DAGs, not a host DAG mount")
    execution_api_env = runtime_target.get("target", {}).get("execution_api_server_url_env")
    airflow_environment = compose.get("x-airflow-env", {})
    execution_api_value = airflow_environment.get("AIRFLOW__CORE__EXECUTION_API_SERVER_URL")
    if execution_api_env != "AIRFLOW_EXECUTION_API_SERVER_URL" or execution_api_env not in str(
        execution_api_value
    ):
        fail("Airflow Execution API URL must use the declared explicit environment setting")
    sender_target = runtime_target.get("managed_services", {}).get("wechat_sender", {})
    if (
        sender_target.get("endpoint_variable") != "WECHAT_SEND_API_URL"
        or sender_target.get("readiness_path") != "/readyz"
        or sender_target.get("deployment_owner") != "android_device_host"
    ):
        fail("WeChat sender health must follow the external device-host runtime contract")

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
        if service_id == "wechat_sender" and service.get("runtime_owner") != "android_device_host":
            fail("wechat_sender runtime owner must be the Android device host")

    if undeclared_variables:
        fail(
            "variables missing from config/config-contracts.yaml: "
            + ", ".join(sorted(undeclared_variables))
        )
    if undeclared_connections:
        fail(
            "connections missing from config/config-contracts.yaml: "
            + ", ".join(sorted(undeclared_connections))
        )

    known_contract_owners = dag_ids | set((manifest.get("shared_contracts") or {}).keys())
    for contract_kind, contract_map in (
        ("variable", variable_contracts),
        ("connection", connection_contracts),
    ):
        for name, contract in contract_map.items():
            if not isinstance(contract, dict):
                fail(f"{contract_kind} contract {name} must be a mapping")
            required_by = contract.get("required_by") or []
            if not isinstance(required_by, list) or not required_by:
                fail(f"{contract_kind} contract {name} requires a non-empty required_by list")
            unknown_owners = sorted(set(required_by) - known_contract_owners)
            if unknown_owners:
                fail(
                    f"{contract_kind} contract {name} has unknown owners: "
                    + ", ".join(unknown_owners)
                )
            if contract_kind == "variable":
                managed = contract.get("managed_by_application") is True
                policy = contract.get("fresh_start_policy")
                if managed and policy not in {"preserve", "reset"}:
                    fail(
                        f"managed variable contract {name} requires "
                        "fresh_start_policy preserve or reset"
                    )
                if not managed and policy is not None:
                    fail(f"static variable contract {name} must not define fresh_start_policy")
                if policy == "reset" and contract.get("type") != "json_list":
                    fail(f"reset variable contract {name} must have type json_list")

    print(
        "active-components: ok "
        f"dags={len(dag_ids)} services={len(active_services)} "
        f"declared_variables={len(contract_names)} "
        f"declared_connections={len(connection_contract_names)}"
    )


if __name__ == "__main__":
    main()
