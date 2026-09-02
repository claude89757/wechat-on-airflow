from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import webapp_deployment_identity  # noqa: E402


class WebappDeploymentIdentityTest(TestCase):
    def test_accepts_exact_healthy_worker_without_d1_payload(self) -> None:
        commit = "a" * 40
        result = webapp_deployment_identity.evaluate_deployment_identity(
            200,
            {
                "ok": True,
                "deploymentCommit": commit,
                "capabilities": {"priorityWeatherBypass": True},
            },
            commit,
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["d1_checked"])

    def test_rejects_wrong_commit_or_unhealthy_worker(self) -> None:
        commit = "a" * 40
        wrong_commit = webapp_deployment_identity.evaluate_deployment_identity(
            200,
            {
                "ok": True,
                "deploymentCommit": "b" * 40,
                "capabilities": {"priorityWeatherBypass": True},
            },
            commit,
        )
        unhealthy = webapp_deployment_identity.evaluate_deployment_identity(
            503,
            {"ok": False, "deploymentCommit": commit},
            commit,
        )
        self.assertFalse(wrong_commit["ok"])
        self.assertFalse(unhealthy["ok"])
