from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

SCRIPTS = Path(__file__).parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import webapp_deployment_identity  # noqa: E402


class WebappDeploymentIdentityTest(TestCase):
    def identity(
        self,
        deployed_commit: str,
        expected_commit: str,
        *,
        healthy: bool = True,
    ) -> dict[str, object]:
        return webapp_deployment_identity.evaluate_deployment_identity(
            200 if healthy else 503,
            {
                "ok": healthy,
                "deploymentCommit": deployed_commit,
                "capabilities": {"priorityWeatherBypass": True},
            },
            expected_commit,
        )

    def test_accepts_exact_healthy_worker_without_d1_payload(self) -> None:
        commit = "a" * 40
        result = self.identity(commit, commit)
        self.assertTrue(result["ok"])
        self.assertFalse(result["d1_checked"])

    def test_rejects_wrong_commit_or_unhealthy_worker(self) -> None:
        commit = "a" * 40
        wrong_commit = self.identity("b" * 40, commit)
        unhealthy = self.identity(commit, commit, healthy=False)
        self.assertFalse(wrong_commit["ok"])
        self.assertFalse(unhealthy["ok"])

    def test_only_an_otherwise_healthy_old_commit_is_propagating(self) -> None:
        commit = "a" * 40
        old_commit = self.identity("b" * 40, commit)
        unhealthy = self.identity("b" * 40, commit, healthy=False)

        self.assertTrue(webapp_deployment_identity.deployment_is_propagating(old_commit))
        self.assertFalse(webapp_deployment_identity.deployment_is_propagating(unhealthy))

    def test_waits_for_the_exact_commit_during_edge_propagation(self) -> None:
        commit = "a" * 40
        responses = iter(
            [
                self.identity("b" * 40, commit),
                self.identity(commit, commit),
            ]
        )
        sleeps: list[float] = []
        times = iter([100.0, 100.0])

        result = webapp_deployment_identity.wait_for_deployment_identity(
            base_url="https://example.test",
            expected_commit=commit,
            propagation_timeout_seconds=90,
            retry_interval_seconds=2,
            inspector=lambda **_kwargs: next(responses),
            monotonic=lambda: next(times),
            sleeper=sleeps.append,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(sleeps, [2])

    def test_does_not_retry_an_unhealthy_service(self) -> None:
        commit = "a" * 40
        calls = 0

        def inspect(**_kwargs):
            nonlocal calls
            calls += 1
            return self.identity(commit, commit, healthy=False)

        result = webapp_deployment_identity.wait_for_deployment_identity(
            base_url="https://example.test",
            expected_commit=commit,
            propagation_timeout_seconds=90,
            retry_interval_seconds=2,
            inspector=inspect,
            monotonic=lambda: 100.0,
            sleeper=lambda _seconds: self.fail("unexpected retry"),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(calls, 1)
