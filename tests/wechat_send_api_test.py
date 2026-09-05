import hashlib
import unittest
from unittest.mock import call, patch

from wechat_airflow.notifications import wechat as wechat_send_api


class FakeResponse:
    status_code = 200
    text = '{"success": true}'

    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {"success": True, "sent_count": 1}
        self.status_code = status_code
        self.text = str(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP request rejected")

    def json(self):
        return self._payload


class WeChatSendApiTest(unittest.TestCase):
    def variable_getter(self, key, default=None, deserialize_json=False):
        values = {
            "WECHAT_SEND_API_URL": "http://sender.example/v1/wechat/send",
            "WECHAT_SEND_DEVICE_NAME": "device-from-variable",
            "WECHAT_SEND_TIMEOUT_SECONDS": "400",
            "WECHAT_SEND_RETRY_COUNT": "1",
            "WECHAT_SEND_RETRY_DELAY_SECONDS": "0",
        }
        return values.get(key, default)

    def idempotency_key(self, receiver, messages, device_name="device-from-variable"):
        return hashlib.sha256("\0".join([receiver, device_name, *messages]).encode()).hexdigest()

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_uses_airflow_variable_endpoint(self, mock_post):
        mock_post.return_value = FakeResponse({"success": True, "sent_count": 2})

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            result = wechat_send_api.send_wechat_text(" 文件传输助手 ", ["hello", "world"])

        self.assertEqual(result["sent_count"], 2)
        mock_post.assert_called_once_with(
            "http://sender.example/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello", "world"],
                "device_name": "device-from-variable",
                "idempotency_key": self.idempotency_key(
                    "文件传输助手",
                    ["hello", "world"],
                ),
            },
            timeout=400,
        )

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_allows_explicit_device_name(self, mock_post):
        mock_post.return_value = FakeResponse()

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            wechat_send_api.send_wechat_text("Zacks", ["hello"], device_name="explicit-device")

        self.assertEqual(mock_post.call_args.kwargs["json"]["device_name"], "explicit-device")
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["idempotency_key"],
            self.idempotency_key("Zacks", ["hello"], "explicit-device"),
        )

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_raises_on_api_failure(self, mock_post):
        mock_post.return_value = FakeResponse(
            {"success": False, "error": "send_failed", "message": "send button missing"},
            status_code=500,
        )

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertIn("send_failed", str(error.exception))
        mock_post.assert_called_once()

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_wechat_text_wraps_request_errors(self, mock_post):
        mock_post.side_effect = wechat_send_api.requests.Timeout("timeout")

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertIn("request failed", str(error.exception))

    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_send_timeout_floors_below_the_device_queue_wait(self, mock_post):
        mock_post.return_value = FakeResponse()

        def getter(key, default=None, deserialize_json=False):
            values = {
                "WECHAT_SEND_API_URL": "http://sender.example/v1/wechat/send",
                "WECHAT_SEND_DEVICE_NAME": "device-from-variable",
                "WECHAT_SEND_TIMEOUT_SECONDS": "30",
                "WECHAT_SEND_RETRY_COUNT": "1",
                "WECHAT_SEND_RETRY_DELAY_SECONDS": "0",
            }
            return values.get(key, default)

        with patch("wechat_airflow.notifications.wechat._get_variable", side_effect=getter):
            wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertEqual(
            mock_post.call_args.kwargs["timeout"],
            wechat_send_api.MIN_SEND_TIMEOUT_SECONDS,
        )

    @patch("wechat_airflow.notifications.wechat.time.sleep")
    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_device_busy_waits_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            FakeResponse(
                {"success": False, "error": "device_busy", "message": "busy"},
                status_code=409,
            ),
            FakeResponse({"success": True, "sent_count": 1}),
        ]

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            result = wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(wechat_send_api.DEVICE_BUSY_RETRY_DELAY_SECONDS)

    @patch("wechat_airflow.notifications.wechat.time.sleep")
    @patch("wechat_airflow.notifications.wechat.requests.post")
    def test_device_busy_retries_before_raising(self, mock_post, mock_sleep):
        mock_post.return_value = FakeResponse(
            {"success": False, "error": "device_busy", "message": "busy"},
            status_code=409,
        )

        with patch(
            "wechat_airflow.notifications.wechat._get_variable", side_effect=self.variable_getter
        ):
            with self.assertRaises(wechat_send_api.WeChatSendApiError) as error:
                wechat_send_api.send_wechat_text("Zacks", ["hello"])

        self.assertEqual(error.exception.error_code, "device_busy")
        self.assertEqual(mock_post.call_count, wechat_send_api.DEVICE_BUSY_RETRY_LIMIT)
        self.assertEqual(
            mock_sleep.call_args_list,
            [call(wechat_send_api.DEVICE_BUSY_RETRY_DELAY_SECONDS)]
            * (wechat_send_api.DEVICE_BUSY_RETRY_LIMIT - 1),
        )

    @patch("wechat_airflow.notifications.wechat.send_wechat_text")
    def test_send_wechat_text_to_chatrooms_normalizes_lines(self, mock_send):
        wechat_send_api.send_wechat_text_to_chatrooms(" A \n\n B ", "hello")

        self.assertEqual(
            [call.args for call in mock_send.call_args_list],
            [("A", ["hello"]), ("B", ["hello"])],
        )

    def test_best_effort_persists_intent_without_device_io(self):
        with (
            patch.object(wechat_send_api, "_get_variable", return_value="device"),
            patch("wechat_airflow.notifications.webapp._host_token", return_value="token"),
            patch.object(
                wechat_send_api.requests,
                "post",
                return_value=FakeResponse({"success": True, "durable": True, "ids": ["x"]}),
            ) as post,
            patch.object(
                wechat_send_api,
                "send_wechat_text",
                side_effect=AssertionError("device I/O in collector"),
            ),
        ):
            result = wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A", "B"], "message", booking_venue_id="tops"
            )
        assert result[0]["queued"] is True
        assert (
            post.call_args.args[0] == "http://zacks-api:8090/zacks-api/api/internal/wechat-enqueue"
        )
        assert post.call_args.kwargs["json"]["receivers"] == ["A", "B"]
        assert post.call_args.kwargs["timeout"] == 5

    def test_best_effort_releases_collector_preclaim_on_persistence_failure(self):
        with (
            patch("wechat_airflow.notifications.webapp._host_token", return_value="token"),
            patch.object(wechat_send_api, "_get_variable", return_value="device"),
            patch.object(wechat_send_api.requests, "post", side_effect=RuntimeError("unavailable")),
            patch.object(wechat_send_api, "_release_subscription_gate_dedupe") as release,
        ):
            result = wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A"], "message", booking_venue_id="tops"
            )
        assert result[0]["success"] is False
        release.assert_called_once_with("tops", "message")

    def test_suppressed_intent_releases_collector_preclaim(self):
        with (
            patch("wechat_airflow.notifications.webapp._host_token", return_value="token"),
            patch.object(wechat_send_api, "_get_variable", return_value="device"),
            patch.object(
                wechat_send_api.requests,
                "post",
                return_value=FakeResponse({"success": True, "suppressed": True}),
            ),
            patch.object(wechat_send_api, "_release_subscription_gate_dedupe") as release,
        ):
            wechat_send_api.send_wechat_text_to_chatrooms_best_effort(
                ["A"], "message", booking_venue_id="tops"
            )
        release.assert_called_once_with("tops", "message")


if __name__ == "__main__":
    unittest.main()
