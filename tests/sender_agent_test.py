import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import sender_agent.app as sender_app
from wechat_sender import SendFailedError, SendResult


class SenderAgentTest(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {"WECHAT_ALLOWED_DEVICE_NAME": "test-device"},
            clear=False,
        )
        self.env_patcher.start()
        self.client = TestClient(sender_app.app)

    def tearDown(self):
        self.env_patcher.stop()

    @patch("sender_agent.app.send_text_messages")
    def test_send_success(self, mock_send):
        mock_send.return_value = SendResult(
            success=True,
            device_name="test-device",
            receiver="文件传输助手",
            sent_count=1,
        )

        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "test-device",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "device_name": "test-device",
                "receiver": "文件传输助手",
                "sent_count": 1,
            },
        )
        mock_send.assert_called_once()
        self.assertIs(
            mock_send.call_args.kwargs["preflight_cleanup"],
            sender_app.cleanup_appium_device,
        )

    def test_defaults_to_local_appium_on_sender_host(self):
        with patch.dict(os.environ, {}, clear=True):
            from sender_agent.app import _appium_url

            self.assertEqual(_appium_url(), "http://127.0.0.1:6002")

    def test_health_reports_required_runtime_configuration(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "service": "wechat-sender-agent",
                "configured": True,
            },
        )

    @patch("sender_agent.app.urlopen")
    def test_readiness_checks_appium_without_using_the_device(self, mock_urlopen):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"value":{"ready":true}}'
        mock_urlopen.return_value.__enter__.return_value = response

        result = self.client.get("/readyz")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["appium_ready"], True)
        mock_urlopen.assert_called_once_with("http://127.0.0.1:6002/status", timeout=5)

    @patch("sender_agent.app.urlopen", side_effect=TimeoutError)
    def test_readiness_reports_appium_failure_without_endpoint_details(self, _mock_urlopen):
        result = self.client.get("/readyz")

        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()["error"], "appium_unavailable")
        self.assertNotIn("127.0.0.1", result.text)

    def test_send_rejects_missing_device_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post(
                "/v1/wechat/send",
                json={
                    "receiver": "test-chat",
                    "messages": ["hello"],
                    "device_name": "test-device",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "service_misconfigured")

    @patch("sender_agent.app.send_text_messages")
    def test_allows_request_without_token(self, mock_send):
        mock_send.return_value = SendResult(
            success=True,
            device_name="test-device",
            receiver="文件传输助手",
            sent_count=1,
        )

        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "test-device",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        mock_send.assert_called_once()

    def test_rejects_wrong_device(self):
        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "other-device",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "device_not_allowed")

    def test_rejects_invalid_messages(self):
        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": [],
                "device_name": "test-device",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_rejects_empty_message_item(self):
        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": [""],
                "device_name": "test-device",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_request")

    @patch("sender_agent.app.device_lock")
    def test_returns_device_busy_when_lock_is_held(self, mock_lock):
        mock_lock.acquire.return_value = False

        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "test-device",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "device_busy")

    @patch("sender_agent.app.send_text_messages")
    def test_maps_sender_failure(self, mock_send):
        mock_send.side_effect = SendFailedError("send button missing")

        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "test-device",
            },
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "send_failed")
        self.assertIn("send button missing", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
