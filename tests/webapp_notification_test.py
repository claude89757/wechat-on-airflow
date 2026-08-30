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
            "fsb_shenyun_watcher.py": "run_check_tennis_courts",
            "fsb_shekou_watcher.py": "run_check_tennis_courts",
            "fsb_xinan_watcher.py": "run_check_tennis_courts",
            "fsb_zhengzhong_watcher.py": "run_check_tennis_courts",
            "fsb_atuoshan_watcher.py": "run_check_tennis_courts",
            "fsb_zonglvquan_watcher.py": "run_check_tennis_courts",
            "fsb_guanhu_watcher.py": "run_check_tennis_courts",
            "fsb_bantian_watcher.py": "run_check_tennis_courts",
            "fsb_shahe_watcher.py": "run_check_tennis_courts",
            "fsb_baoshui_watcher.py": "run_check_tennis_courts",
            "fsb_nanyou_watcher.py": "run_check_tennis_courts",
            "fsb_xinqiao_watcher.py": "run_check_tennis_courts",
            "fsb_yifangcheng_watcher.py": "run_check_tennis_courts",
            "fsb_qilin_watcher.py": "run_check_tennis_courts",
            "fsb_maozhouhe_watcher.py": "run_check_tennis_courts",
            "ppba_watcher.py": "run_check_tennis_courts",
            "tyzx_watcher.py": "run_check_tennis_courts",
            "dashahe_free_watcher.py": "run_check_dashahe_free_courts",
            "dsh_ydmap_watcher.py": "run_check_tennis_courts",
        }
        pospal_wrappers = {
            "fsb_shenyun_watcher.py",
            "fsb_shekou_watcher.py",
            "fsb_xinan_watcher.py",
            "fsb_zhengzhong_watcher.py",
            "fsb_atuoshan_watcher.py",
            "fsb_zonglvquan_watcher.py",
            "fsb_guanhu_watcher.py",
            "fsb_bantian_watcher.py",
            "fsb_shahe_watcher.py",
            "fsb_baoshui_watcher.py",
            "fsb_nanyou_watcher.py",
            "fsb_xinqiao_watcher.py",
            "fsb_yifangcheng_watcher.py",
            "fsb_qilin_watcher.py",
            "fsb_maozhouhe_watcher.py",
        }
        watcher_root = Path(__file__).parents[1] / "src" / "wechat_airflow" / "venues"
        self.assertEqual(
            set(watchers),
            {path.name for path in watcher_root.glob("*_watcher.py")},
        )

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
                if filename in pospal_wrappers:
                    self.assertEqual([name for _, name in calls], ["run_check"])
                    continue
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

        pospal_source = (watcher_root / "pospal_venue.py").read_text(encoding="utf-8")
        self.assertNotIn("notifications.email", pospal_source)
        pospal_tree = ast.parse(pospal_source)
        pospal_function = next(
            node
            for node in pospal_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_check"
        )
        pospal_calls = [
            (
                node.lineno,
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else "",
            )
            for node in ast.walk(pospal_function)
            if isinstance(node, ast.Call)
        ]
        pospal_publish = [
            line for line, name in pospal_calls if name == "publish_venue_observation"
        ]
        pospal_wechat = [line for line, name in pospal_calls if name == "enqueue_wechat_message"]
        self.assertTrue(pospal_publish)
        self.assertTrue(pospal_wechat)
        self.assertLess(max(pospal_publish), min(pospal_wechat))

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
            observation_scope="check_and_notify_day_0",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["observation_scope"], "check_and_notify_day_0")
        request = post.call_args
        self.assertEqual(request.kwargs["timeout"], 3)
        self.assertEqual(
            request.kwargs["headers"]["Authorization"],
            "Bearer secret-token",
        )
        self.assertEqual(request.kwargs["json"]["venue_id"], "szw")
        self.assertEqual(
            request.kwargs["json"]["observation_scope"],
            "check_and_notify_day_0",
        )
        self.assertEqual(len(request.kwargs["json"]["slots"]), 1)

    @patch("wechat_airflow.notifications.webapp.requests.post")
    @patch(
        "wechat_airflow.notifications.webapp._current_observation_scope",
        return_value="check_and_notify_day_2",
    )
    @patch("wechat_airflow.notifications.webapp._get_variable")
    def test_uses_current_airflow_task_as_default_scope(
        self,
        get_variable,
        _current_observation_scope,
        post,
    ):
        values = {
            webapp.WEBAPP_OBSERVATION_API_URL_VAR: "https://example.test/api/internal/observations",
            webapp.WEBAPP_OBSERVATION_API_TOKEN_VAR: "secret-token",
        }
        get_variable.side_effect = lambda key, default=None: values.get(key, default)
        response = MagicMock()
        response.raise_for_status.return_value = None
        post.return_value = response

        result = webapp.publish_venue_observation(
            "szw",
            "深圳湾",
            [],
            healthy=True,
        )

        self.assertTrue(result["success"])
        _current_observation_scope.assert_called_once_with()
        self.assertEqual(
            post.call_args.kwargs["json"]["observation_scope"],
            "check_and_notify_day_2",
        )

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
