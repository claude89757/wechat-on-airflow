import sys
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
