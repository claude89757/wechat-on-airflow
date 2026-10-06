from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_airflow_constraints", ROOT / "scripts/prepare_airflow_constraints.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_only_cryptography_constraint_changes() -> None:
    upstream = "# Airflow constraints\nparamiko==3.5.1\ncryptography==48.0.1\ncffi==2.0.0\n"
    requirements = (ROOT / "docker/airflow/requirements.txt").read_text()
    assert MODULE.patch_constraints(upstream, requirements) == upstream.replace(
        "cryptography==48.0.1", "cryptography==50.0.1"
    )


@pytest.mark.parametrize("content", ["", "cryptography==48.0.1\ncryptography==49.0.0\n"])
def test_missing_or_duplicate_upstream_pin_fails_closed(content: str) -> None:
    with pytest.raises(ValueError, match="upstream cryptography constraint"):
        MODULE.patch_constraints(content, "cryptography==50.0.1\n")


@pytest.mark.parametrize("content", ["", "cryptography==50.0.1\ncryptography==50.0.1\n"])
def test_missing_or_duplicate_security_pin_fails_closed(content: str) -> None:
    with pytest.raises(ValueError, match="explicit cryptography security pin"):
        MODULE.patch_constraints("cryptography==48.0.1\n", content)


def test_airflow_build_uses_patched_constraints_and_checks_dependencies() -> None:
    dockerfile = (ROOT / "docker/airflow/Dockerfile").read_text()
    assert 'python /tmp/prepare_airflow_constraints.py "${CONSTRAINTS_URL}"' in dockerfile
    assert "--constraint /tmp/constraints-airflow.txt" in dockerfile
    assert "--requirement /tmp/requirements-airflow.txt" in dockerfile
    assert "&& pip check" in dockerfile
