import ast
from pathlib import Path


def test_task_sdk_variable_get_uses_airflow3_default_keyword():
    source_root = Path(__file__).parents[1] / "src"
    violations = []

    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "Variable":
                continue
            for keyword in node.keywords:
                if keyword.arg == "default_var":
                    violations.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert not violations, (
        "airflow.sdk.Variable.get() uses default= in Airflow 3; invalid calls: "
        + ", ".join(violations)
    )
