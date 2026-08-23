from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_active_components  # noqa: E402


class AirflowRuntimeContractTest(TestCase):
    def setUp(self) -> None:
        self.target = {
            "airflow": "3.3.0",
            "python": "3.12",
            "base_image": "apache/airflow:3.3.0-python3.12@sha256:" + "a" * 64,
            "providers": {
                "apache-airflow-providers-celery": "3.21.0",
                "apache-airflow-providers-standard": "1.15.0",
            },
        }
        self.production = {
            "current_airflow": "2.10.5",
            "target_airflow": "3.3.0",
            "python": "3.12",
        }
        self.dockerfile = "\n".join(
            (
                f"FROM {self.target['base_image']}",
                "ARG AIRFLOW_VERSION=3.3.0",
                "ARG PYTHON_VERSION=3.12",
            )
        )
        self.requirements = "\n".join(
            (
                "apache-airflow-providers-celery==3.21.0",
                "apache-airflow-providers-standard==1.15.0",
            )
        )
        self.compose_image = "${AIRFLOW_IMAGE_NAME:-wechat-on-airflow:3.3.0}"

    def validate(self, **overrides: object) -> None:
        values = {
            "target": self.target,
            "production": self.production,
            "dockerfile": self.dockerfile,
            "airflow_requirements_text": self.requirements,
            "compose_image": self.compose_image,
        }
        values.update(overrides)
        check_active_components.validate_airflow_runtime_contract(**values)

    def test_allows_staged_upgrade_when_current_version_differs(self) -> None:
        self.validate()

    def test_rejects_missing_base_image(self) -> None:
        target = {**self.target, "base_image": ""}

        with self.assertRaises(SystemExit):
            self.validate(target=target)

    def test_rejects_python_version_drift(self) -> None:
        production = {**self.production, "python": "3.11"}

        with self.assertRaises(SystemExit):
            self.validate(production=production)

    def test_rejects_extra_provider_requirement(self) -> None:
        requirements = self.requirements + "\napache-airflow-providers-fab==3.7.1\n"

        with self.assertRaises(SystemExit):
            self.validate(airflow_requirements_text=requirements)

    def test_rejects_commented_dockerfile_contract(self) -> None:
        dockerfile = "\n".join(f"# {line}" for line in self.dockerfile.splitlines())

        with self.assertRaises(SystemExit):
            self.validate(dockerfile=dockerfile)
