import ast
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from wechat_airflow.notifications import webapp


class WebappNotificationTest(TestCase):
    def test_venue_watchers_publish_webapp_before_wechat_without_fixed_email(self):
        watchers = {
            "szw_watcher.py": "check_and_notify_for_day",
            "jdwx_watcher.py": "run_check_tennis_courts",
            "sysh_watcher.py": "run_check_tennis_courts",
            "tops_watcher.py": "run_check_tennis_courts",
            "fsb_watcher.py": "run_check_tennis_courts",
            "tyzx_watcher.py": "run_check_tennis_courts",
            "dashahe_free_watcher.py": "run_check_dashahe_free_courts",
        }
        watcher_root = Path(__file__).parents[1] / "src" / "wechat_airflow" / "venues"

        for filename, function_name in watchers.items():
            with self.subTest(filename=filename):
                source = (watcher_root / filename).read_text(encoding="utf-8")
                self.assertNotIn("notifications.email", source)
                self.assertNotIn("_EMAIL_LIST", source)
                self.assertNotIn("send_venue_email_batch", source)

                tree = ast.parse(source)
                function = next(
                    node
                    for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == function_name
                )
                calls = [
                    (
                        node.lineno,
                        node.func.id
                        if isinstance(node.func, ast.Name)
                        else node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else "",
                    )
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                ]
                publish_lines = [
                    line for line, name in calls if name == "publish_venue_observation"
                ]
                wechat_lines = [
                    line
                    for line, name in calls
                    if name
                    in {
                        "enqueue_wechat_message",
                        "send_wechat_text_to_chatrooms_best_effort",
                    }
                ]
                self.assertTrue(publish_lines)
                self.assertTrue(wechat_lines)
                self.assertLess(max(publish_lines), min(wechat_lines))

    def test_flattens_slots_and_normalizes_midnight(self):
        result = webapp.flatten_court_slots(
            "2026-07-30",
            {
                "1号场": [["18:00", "19:00"], ["23:00", "24:00"]],
                "": [["10:00", "11:00"]],
            },
        )

        self.assertEqual(
            result,
            [
                {
                    "date": "2026-07-30",
                    "court_name": "1号场",
                    "start_time": "18:00",
                    "end_time": "19:00",
                },
                {
                    "date": "2026-07-30",
                    "court_name": "1号场",
                    "start_time": "23:00",
                    "end_time": "23:59",
                },
            ],
        )

    @patch("wechat_airflow.notifications.webapp.requests.post")
    @patch("wechat_airflow.notifications.webapp._get_variable")
    def test_publishes_bearer_authenticated_payload(self, get_variable, post):
        values = {
            webapp.WEBAPP_OBSERVATION_API_URL_VAR: "https://example.test/api/internal/observations",
            webapp.WEBAPP_OBSERVATION_API_TOKEN_VAR: "secret-token",
            webapp.WEBAPP_OBSERVATION_TIMEOUT_SECONDS_VAR: "3",
        }
        get_variable.side_effect = lambda key, default=None: values.get(key, default)
        response = MagicMock()
        response.raise_for_status.return_value = None
        post.return_value = response

        result = webapp.publish_venue_observation(
            "szw",
            "深圳湾",
            [
                {
                    "date": "2026-07-30",
                    "court_name": "1号场",
                    "start_time": "18:00",
                    "end_time": "19:00",
                }
            ],
            healthy=True,
            checked_at=datetime(2026, 7, 29, 2, 0, tzinfo=UTC),
        )

        self.assertTrue(result["success"])
        request = post.call_args
        self.assertEqual(request.kwargs["timeout"], 3)
        self.assertEqual(
            request.kwargs["headers"]["Authorization"],
            "Bearer secret-token",
        )
        self.assertEqual(request.kwargs["json"]["venue_id"], "szw")
        self.assertEqual(len(request.kwargs["json"]["slots"]), 1)

    @patch("wechat_airflow.notifications.webapp.requests.post")
    @patch("wechat_airflow.notifications.webapp._get_variable")
    def test_network_failure_does_not_raise(self, get_variable, post):
        get_variable.side_effect = lambda key, default=None: {
            webapp.WEBAPP_OBSERVATION_API_URL_VAR: "https://example.test/observations",
            webapp.WEBAPP_OBSERVATION_API_TOKEN_VAR: "secret-token",
        }.get(key, default)
        post.side_effect = requests_error = RuntimeError("unavailable")

        result = webapp.publish_venue_observation(
            "szw",
            "深圳湾",
            [],
            healthy=False,
            error="upstream failed",
        )

        self.assertFalse(result["success"])
        self.assertIn(str(requests_error), result["error"])

    @patch("wechat_airflow.notifications.webapp._get_variable", return_value="")
    def test_missing_configuration_is_a_clean_skip(self, _get_variable):
        result = webapp.publish_venue_observation(
            "szw",
            "深圳湾",
            [],
            healthy=True,
        )

        self.assertTrue(result["skipped"])
