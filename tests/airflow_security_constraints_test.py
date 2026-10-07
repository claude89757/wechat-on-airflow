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
UPSTREAM = (
    "# Airflow constraints\nparamiko==3.5.1\ncryptography==48.0.1\n"
    "gcloud-aio-auth==5.4.4\npyOpenSSL==26.2.0\ncffi==2.0.0\n"
)
REQUIREMENTS = (ROOT / "docker/airflow/requirements.txt").read_text()


def test_only_reviewed_security_constraints_change() -> None:
    assert MODULE.patch_constraints(UPSTREAM, REQUIREMENTS) == (
        UPSTREAM.replace("cryptography==48.0.1", "cryptography==50.0.1")
        .replace("gcloud-aio-auth==5.4.4", "gcloud-aio-auth==5.5.0")
        .replace("pyOpenSSL==26.2.0", "pyOpenSSL==26.4.0")
    )


@pytest.mark.parametrize("package", MODULE.SECURITY_PINS)
@pytest.mark.parametrize("copies", [0, 2])
def test_missing_or_duplicate_upstream_pin_fails_closed(package: str, copies: int) -> None:
    pin = next(line for line in UPSTREAM.splitlines(keepends=True) if line.startswith(package))
    with pytest.raises(ValueError, match=f"upstream {package} constraint"):
        MODULE.patch_constraints(UPSTREAM.replace(pin, pin * copies), REQUIREMENTS)


@pytest.mark.parametrize("package", MODULE.SECURITY_PINS)
@pytest.mark.parametrize("copies", [0, 2])
def test_missing_or_duplicate_security_pin_fails_closed(package: str, copies: int) -> None:
    pin = next(line for line in REQUIREMENTS.splitlines(keepends=True) if line.startswith(package))
    with pytest.raises(ValueError, match=f"explicit {package} security pin"):
        MODULE.patch_constraints(UPSTREAM, REQUIREMENTS.replace(pin, pin * copies))


def test_airflow_build_uses_patched_constraints_and_checks_dependencies() -> None:
    dockerfile = (ROOT / "docker/airflow/Dockerfile").read_text()
    assert 'python /tmp/prepare_airflow_constraints.py "${CONSTRAINTS_URL}"' in dockerfile
    assert "--constraint /tmp/constraints-airflow.txt" in dockerfile
    assert "--requirement /tmp/requirements-airflow.txt" in dockerfile
    assert "&& pip check" in dockerfile
