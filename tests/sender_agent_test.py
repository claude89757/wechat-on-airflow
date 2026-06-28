import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import sender_agent.app as sender_app
from wechat_sender import SendFailedError, SendResult


class SenderAgentTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(sender_app.app)

    @patch("sender_agent.app.send_text_messages")
    def test_send_success(self, mock_send):
        mock_send.return_value = SendResult(
            success=True,
            device_name="971bd67c0107",
            receiver="文件传输助手",
            sent_count=1,
        )

        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "success": True,
                "device_name": "971bd67c0107",
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

    @patch("sender_agent.app.send_text_messages")
    def test_allows_request_without_token(self, mock_send):
        mock_send.return_value = SendResult(
            success=True,
            device_name="971bd67c0107",
            receiver="文件传输助手",
            sent_count=1,
        )

        response = self.client.post(
            "/v1/wechat/send",
            json={
                "receiver": "文件传输助手",
                "messages": ["hello"],
                "device_name": "971bd67c0107",
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
                "device_name": "971bd67c0107",
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
                "device_name": "971bd67c0107",
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
                "device_name": "971bd67c0107",
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
                "device_name": "971bd67c0107",
            },
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "send_failed")
        self.assertIn("send button missing", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
