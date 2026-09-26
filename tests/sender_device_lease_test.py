import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sender_agent.app as sender_app
from sender_agent.device_lease import DeviceLease


class DeviceLeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"WECHAT_DEVICE_LOCK_DIR": self.tmp.name})
        self.env.start()
        sender_app.reset_runtime_state()

    def tearDown(self):
        sender_app.reset_runtime_state()
        self.env.stop()
        self.tmp.cleanup()

    def test_lease_excludes_another_process_and_releases(self):
        lease = DeviceLease("phone")
        self.assertTrue(lease.acquire())
        code = "from sender_agent.device_lease import DeviceLease; import sys; sys.exit(0 if DeviceLease('phone').acquire() else 7)"
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 7)
        self.assertEqual(Path(lease.path).stat().st_mode & 0o777, 0o660)
        lease.release()
        self.assertEqual(subprocess.run([sys.executable, "-c", code]).returncode, 0)

    def test_timer_cannot_close_an_active_send_or_replacement(self):
        operator = MagicMock()
        sender_app._warm_operator = operator
        generation = sender_app._warm_generation
        with sender_app.device_lock:
            worker = threading.Thread(target=sender_app._expire_warm_operator, args=(generation,))
            worker.start()
            operator.close.assert_not_called()
            sender_app._cancel_warm_idle_timer()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        operator.close.assert_not_called()

    def test_idle_expiry_releases_the_shared_lease(self):
        lease = DeviceLease("phone")
        lease.acquire()
        sender_app._device_lease = lease
        sender_app._warm_operator = MagicMock()
        with patch("sender_agent.app.Timer") as timer:
            sender_app._arm_warm_idle_timer()
            timer.assert_called_once()
        sender_app._expire_warm_operator(sender_app._warm_generation)
        self.assertIsNone(sender_app._warm_operator)
        self.assertIsNone(lease.fd)

    def test_cleanup_error_still_releases_phone(self):
        lease = DeviceLease("phone")
        lease.acquire()
        sender_app._device_lease = lease
        sender_app._warm_operator = MagicMock()
        sender_app._warm_operator.close.side_effect = OSError("disconnected")
        sender_app.reset_runtime_state()
        self.assertIsNone(lease.fd)

    def test_missing_lock_directory_fails_closed(self):
        with patch.dict(os.environ, {"WECHAT_DEVICE_LOCK_DIR": self.tmp.name + "/missing"}):
            with self.assertRaises(FileNotFoundError):
                DeviceLease("phone").acquire()


class SenderBusyContractTest(unittest.TestCase):
    def test_busy_phone_does_not_claim_or_submit_message(self):
        sender_app.reset_runtime_state()
        request = sender_app.SendRequest(receiver="test", messages=["hello"], device_name="phone")
        with (
            patch.dict(os.environ, {"WECHAT_ALLOWED_DEVICE_NAME": "phone"}),
            patch("sender_agent.app.DeviceLease") as lease,
            patch("sender_agent.app.ledger.claim") as claim,
            patch("sender_agent.app.send_text_messages") as send,
        ):
            lease.return_value.acquire.return_value = False
            result = sender_app.send_wechat(request)
        self.assertEqual(result.status_code, 409)
        claim.assert_not_called()
        send.assert_not_called()
