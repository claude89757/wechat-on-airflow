import sys
import unittest
from pathlib import Path
from unittest.mock import call
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))

from utils import wechat_send_api


class FakeResponse:
    status_code = 200
    text = '{"success": true}'

    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {"success": True, "sent_count": 1}
        self.status_code = status_code
        self.text = str(self._payload)

    def json(self):
        return self._payload


class WeChatSendApiTest(unittest.TestCase):
    def variable_getter(self, key, default_var=None, deserialize_json=False):
        values = {
            "WECHAT_SEND_API_URL": "http://sender.example/v1/wechat/send",
            "WECHAT_SEND_DEVICE_NAME": "device-from-variable",
            "WECHAT_SEND_TIMEOUT_SECONDS": "30",
            "WECHAT_SEND_RETRY_COUNT": "1",
            "WECHAT_SEND_RETRY_DELAY_SECONDS": "0",
        }
        return values.get(key, default_var)

    @patch("utils.wechat_send_api.requests.post")
    def test_send_wechat_text_uses_airflow_variable_endpoint(self, mock_post):
        mock_post.return_value = FakeResponse({"success": True, "sent_count": 2})

        with patch("utils.wechat_send_api._get_variable", side_effect=self.variable_getter):
            result = wechat_send_api.send_wechat_text(" 文件传输助手 ", ["hello", "world"])

        self.assertEqual(result["sent_count"], 2)
        mock_post.assert_called_once_with(
            "http://sender.example/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello", "world"],
                "device_name": "device-from-variable",
            },
            timeout=30,
        )

    @patch("utils.wechat_send_api.requests.post")
    def test_send_wechat_text_allows_explicit_device_name(self, mock_post):
        mock_post.return_value = FakeResponse()

        with patch("utils.wechat_send_api._get_variable", side_effect=self.variable_getter):
            wechat_send_api.send_wechat_text("Zacks", ["hello"], device_name="explicit-device")

        self.assertEqual(mock_post.call_args.kwargs["json"]["device_name"], "explicit-device")

    @patch("utils.wechat_send_api.requests.post")
    def test_send_wechat_text_raises_on_api_failure(self, mock_post):
        mock_post.return_value = FakeResponse(
            {"success": False, "error": "device_busy", "message": "busy"},
            status_code=409,
        )

        with patch("utils.wechat_send_api._get_variable", side_effect=self.variable_getter):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertIn("device_busy", str(error.exception))

    @patch("utils.wechat_send_api.requests.post")
    def test_send_wechat_text_wraps_request_errors(self, mock_post):
        mock_post.side_effect = wechat_send_api.requests.Timeout("timeout")

        with patch("utils.wechat_send_api._get_variable", side_effect=self.variable_getter):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertIn("request failed", str(error.exception))

    @patch("utils.wechat_send_api.send_wechat_text")
    def test_send_wechat_text_to_chatrooms_normalizes_lines(self, mock_send):
        wechat_send_api.send_wechat_text_to_chatrooms(" A \n\n B ", "hello")

        self.assertEqual(
            [call.args for call in mock_send.call_args_list],
            [("A", ["hello"]), ("B", ["hello"])],
        )

    def test_best_effort_send_continues_after_failure_and_records_fallback(self):
        variables = {
            "WECHAT_SEND_FALLBACK_OUTBOX": [],
            "WECHAT_SEND_FALLBACK_MAX_ITEMS": "200",
        }

        def get_variable(key, default_var=None, deserialize_json=False):
            return variables.get(key, default_var)

        def set_variable(key, value, serialize_json=False):
            variables[key] = value

        with (
            patch("utils.wechat_send_api._get_variable", side_effect=get_variable),
            patch("utils.wechat_send_api._set_variable", side_effect=set_variable),
            patch(
                "utils.wechat_send_api.send_wechat_text",
                side_effect=[
                    wechat_send_api.WeChatSendApiError("sender unavailable"),
                    {"success": True, "sent_count": 1},
                ],
            ) as mock_send,
            patch("utils.wechat_send_api._utc_now", return_value="2026-07-14T15:00:00+00:00"),
        ):
            results = wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A", "B"],
                "hello",
                source="test-dag",
            )

        self.assertEqual(mock_send.call_args_list, [call("A", ["hello"], device_name=None), call("B", ["hello"], device_name=None)])
        self.assertEqual([result["success"] for result in results], [False, True])
        self.assertEqual(len(variables["WECHAT_SEND_FALLBACK_OUTBOX"]), 1)
        self.assertEqual(variables["WECHAT_SEND_FALLBACK_OUTBOX"][0]["receiver"], "A")
        self.assertEqual(variables["WECHAT_SEND_FALLBACK_OUTBOX"][0]["source"], "test-dag")

    def test_best_effort_send_merges_duplicate_fallback_entries(self):
        variables = {
            "WECHAT_SEND_FALLBACK_OUTBOX": [],
            "WECHAT_SEND_FALLBACK_MAX_ITEMS": "200",
        }

        def get_variable(key, default_var=None, deserialize_json=False):
            return variables.get(key, default_var)

        def set_variable(key, value, serialize_json=False):
            variables[key] = value

        with (
            patch("utils.wechat_send_api._get_variable", side_effect=get_variable),
            patch("utils.wechat_send_api._set_variable", side_effect=set_variable),
            patch(
                "utils.wechat_send_api.send_wechat_text",
                side_effect=wechat_send_api.WeChatSendApiError("sender unavailable"),
            ),
            patch(
                "utils.wechat_send_api._utc_now",
                side_effect=["2026-07-14T15:00:00+00:00", "2026-07-14T15:01:00+00:00"],
            ),
        ):
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(["A"], "hello", source="test-dag")
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(["A"], "hello", source="test-dag")

        fallback = variables["WECHAT_SEND_FALLBACK_OUTBOX"]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["attempt_count"], 2)
        self.assertEqual(fallback[0]["first_failed_at"], "2026-07-14T15:00:00+00:00")
        self.assertEqual(fallback[0]["last_failed_at"], "2026-07-14T15:01:00+00:00")

    @patch("utils.wechat_send_api._record_failed_send", side_effect=RuntimeError("variable unavailable"))
    @patch(
        "utils.wechat_send_api.send_wechat_text",
        side_effect=wechat_send_api.WeChatSendApiError("sender unavailable"),
    )
    def test_best_effort_send_swallows_fallback_persistence_failure(self, mock_send, mock_record):
        results = wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
            ["A"],
            "hello",
            source="test-dag",
        )

        self.assertEqual(results[0]["success"], False)
        mock_send.assert_called_once_with("A", ["hello"], device_name=None)
        mock_record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
