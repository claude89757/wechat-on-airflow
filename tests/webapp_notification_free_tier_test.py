from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from wechat_airflow.notifications import webapp
from wechat_airflow.notifications.observation_cache import ObservationDeliveryDecision


class WebappNotificationFreeTierTest(TestCase):
    def variables(self, key, default=None, deserialize_json=False):
        values = {
            webapp.WEBAPP_OBSERVATION_API_URL_VAR: "https://example.test/api/internal/observations",
            webapp.WEBAPP_OBSERVATION_API_TOKEN_VAR: "secret-token",
            webapp.WEBAPP_OBSERVATION_TIMEOUT_SECONDS_VAR: "3",
        }
        return values.get(key, default)

    def test_recent_unchanged_success_skips_the_network(self) -> None:
        gate = {
            "allowed": True,
            "evaluated_at": "2026-09-02T09:00:00+00:00",
            "valid_until": "2026-09-02T09:10:00+00:00",
            "revision": 123,
        }
        decision = ObservationDeliveryDecision(
            "skip_success",
            "szw:day-0",
            "a" * 64,
            gate,
            True,
        )
        with (
            patch.object(webapp, "_get_variable", side_effect=self.variables),
            patch.object(webapp, "decide_observation_delivery", return_value=decision),
            patch.object(webapp.requests, "post") as post,
        ):
            result = webapp.publish_venue_observation(
                "szw",
                "深圳湾",
                [],
                healthy=True,
                observation_scope="day-0",
            )

        post.assert_not_called()
        self.assertTrue(result["success"])
        self.assertTrue(result["local_deduplicated"])
        self.assertEqual(result["wechat_gate"], gate)

    def test_recent_failure_uses_bounded_retry_without_network(self) -> None:
        decision = ObservationDeliveryDecision(
            "skip_retry",
            "szw:day-0",
            "a" * 64,
            None,
            True,
        )
        with (
            patch.object(webapp, "_get_variable", side_effect=self.variables),
            patch.object(webapp, "decide_observation_delivery", return_value=decision),
            patch.object(webapp.requests, "post") as post,
        ):
            result = webapp.publish_venue_observation(
                "szw",
                "深圳湾",
                [],
                healthy=True,
                observation_scope="day-0",
            )

        post.assert_not_called()
        self.assertFalse(result["success"])
        self.assertTrue(result["deferred"])

    def test_forwarded_result_is_recorded_after_success(self) -> None:
        decision = ObservationDeliveryDecision(
            "forward",
            "szw:day-0",
            "a" * 64,
            None,
            True,
        )
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "wechatGate": {
                "allowed": False,
                "evaluatedAt": "2026-09-02T09:00:00Z",
                "validUntil": "2026-09-02T09:10:00Z",
                "revision": 123,
            }
        }
        with (
            patch.object(webapp, "_get_variable", side_effect=self.variables),
            patch.object(webapp, "decide_observation_delivery", return_value=decision),
            patch.object(webapp, "record_observation_result") as record,
            patch.object(webapp, "_cache_gate"),
            patch.object(webapp.requests, "post", return_value=response),
        ):
            result = webapp.publish_venue_observation(
                "szw",
                "深圳湾",
                [],
                healthy=True,
                observation_scope="day-0",
            )

        self.assertTrue(result["success"])
        record.assert_called_once()
        self.assertTrue(record.call_args.kwargs["success"])
        self.assertEqual(record.call_args.kwargs["gate"]["revision"], 123)

    def test_unchanged_gate_does_not_rewrite_airflow_metadata(self) -> None:
        gate = {
            "allowed": True,
            "evaluated_at": "2026-09-02T09:00:00+00:00",
            "valid_until": "2026-09-02T09:10:00+00:00",
            "revision": 123,
        }
        with (
            patch.object(
                webapp,
                "_get_variable",
                return_value={"szw": gate},
            ),
            patch.object(webapp, "_set_variable") as set_variable,
        ):
            webapp._cache_gate("szw", gate)

        set_variable.assert_not_called()
