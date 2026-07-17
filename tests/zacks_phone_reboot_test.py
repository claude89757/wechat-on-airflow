import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from wechat_airflow.clients import android_device as ssh_control

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_HOST_KEY_SHA256 = "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


class FakeHostKey:
    def __init__(self, value: bytes) -> None:
        self.value = value

    def asbytes(self) -> bytes:
        return self.value


def load_module(relative_path: str, module_name: str):
    module_path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def install_dependency_stubs():
    if "paramiko" not in sys.modules:
        fake_paramiko = types.SimpleNamespace(
            SSHClient=object,
            AutoAddPolicy=object,
        )
        sys.modules["paramiko"] = fake_paramiko

    if "airflow" not in sys.modules:

        class FakeDAG:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakeOperator:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def __rshift__(self, other):
                return other

        airflow_module = types.ModuleType("airflow")
        sys.modules["airflow"] = airflow_module

        airflow_sdk = types.ModuleType("airflow.sdk")
        airflow_sdk.DAG = FakeDAG
        airflow_sdk.Variable = types.SimpleNamespace(get=lambda *args, **kwargs: [])
        sys.modules["airflow.sdk"] = airflow_sdk

        airflow_providers = types.ModuleType("airflow.providers")
        sys.modules["airflow.providers"] = airflow_providers
        airflow_standard = types.ModuleType("airflow.providers.standard")
        sys.modules["airflow.providers.standard"] = airflow_standard
        airflow_standard_operators = types.ModuleType("airflow.providers.standard.operators")
        sys.modules["airflow.providers.standard.operators"] = airflow_standard_operators

        airflow_operators_python = types.ModuleType("airflow.providers.standard.operators.python")
        airflow_operators_python.PythonOperator = FakeOperator
        sys.modules["airflow.providers.standard.operators.python"] = airflow_operators_python


install_dependency_stubs()

zacks_reboot = load_module(
    "src/wechat_airflow/maintenance/zacks_phone_reboot.py",
    "zacks_phone_reboot",
)


class ZacksPhoneRebootTest(unittest.TestCase):
    def test_parse_adb_devices_output_detects_exact_device(self):
        output = "\n".join(
            [
                "List of devices attached",
                "ZY22GVV5Z2\tdevice",
                "emulator-5554\toffline",
            ]
        )

        self.assertTrue(ssh_control.parse_adb_devices_output(output, "ZY22GVV5Z2"))
        self.assertFalse(ssh_control.parse_adb_devices_output(output, "emulator-5554"))
        self.assertFalse(ssh_control.parse_adb_devices_output(output, "missing-device"))

    def test_get_device_id_by_adb_only_keeps_device_state(self):
        output = "\n".join(
            [
                "List of devices attached",
                "device-ok\tdevice",
                "device-offline\toffline",
                "device-unauth\tunauthorized",
            ]
        )

        with patch.object(ssh_control, "exec_cmd_by_ssh", return_value=(output, "")):
            result = ssh_control.get_device_id_by_adb(
                host="127.0.0.1",
                port=22,
                username="user",
                password="pass",
                host_key_sha256=TEST_HOST_KEY_SHA256,
            )

        self.assertEqual(result, ["device-ok"])

    def test_is_boot_completed_output_accepts_trimmed_one(self):
        self.assertTrue(ssh_control.is_boot_completed_output("1\n"))
        self.assertTrue(ssh_control.is_boot_completed_output(" 1 \r\n"))
        self.assertFalse(ssh_control.is_boot_completed_output("0\n"))
        self.assertFalse(ssh_control.is_boot_completed_output(""))

    def test_pinned_host_key_policy_accepts_only_exact_sha256_fingerprint(self):
        host_key = FakeHostKey(b"expected-host-key")
        fingerprint = ssh_control.sha256_host_key_fingerprint(host_key)
        policy = ssh_control.PinnedSHA256HostKeyPolicy(fingerprint)

        policy.missing_host_key(None, "device-host", host_key)

        with self.assertRaises(ssh_control.paramiko.SSHException):
            policy.missing_host_key(None, "device-host", FakeHostKey(b"unexpected-host-key"))

    def test_normalize_sha256_host_key_rejects_malformed_values(self):
        with self.assertRaises(ValueError):
            ssh_control.normalize_sha256_host_key("MD5:invalid")
        with self.assertRaises(ValueError):
            ssh_control.normalize_sha256_host_key("SHA256:not-a-valid-digest")

    def test_ssh_connection_pins_host_key_and_disables_sha1(self):
        ssh_client = MagicMock()
        ssh_client.connect.side_effect = RuntimeError("stop after connection options")

        with (
            patch.object(ssh_control.paramiko, "SSHClient", return_value=ssh_client),
            patch.object(ssh_control.LOGGER, "exception"),
        ):
            result = ssh_control.exec_cmd_by_ssh_with_status(
                host="device-host",
                port=22,
                username="user",
                password="pass",
                host_key_sha256=TEST_HOST_KEY_SHA256,
                cmd="true",
            )

        self.assertEqual(result, (None, "stop after connection options", None))
        policy = ssh_client.set_missing_host_key_policy.call_args.args[0]
        self.assertIsInstance(policy, ssh_control.PinnedSHA256HostKeyPolicy)
        connect_options = ssh_client.connect.call_args.kwargs
        self.assertFalse(connect_options["allow_agent"])
        self.assertFalse(connect_options["look_for_keys"])
        self.assertEqual(
            connect_options["disabled_algorithms"],
            {"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )

    def test_find_zacks_appium_server_prefers_explicit_identifier(self):
        configs = [
            {"wx_name": "other", "device_name": "device-1"},
            {"wx_user_id": "zacks", "device_name": "device-2"},
        ]

        result = zacks_reboot.find_zacks_appium_server(configs)

        self.assertEqual(result["device_name"], "device-2")

    def test_find_zacks_appium_server_raises_without_target_match(self):
        configs = [
            {"wx_name": "first", "device_name": "device-1"},
            {"wx_name": "second", "device_name": "device-2"},
        ]

        with self.assertRaises(ValueError):
            zacks_reboot.find_zacks_appium_server(configs)

    def test_reboot_device_via_ssh_adb_returns_false_when_ssh_fails(self):
        with patch.object(
            ssh_control, "exec_cmd_by_ssh_with_status", return_value=(None, None, None)
        ):
            result = ssh_control.reboot_device_via_ssh_adb(
                device_ip="127.0.0.1",
                username="user",
                password="pass",
                device_serial="device-1",
                host_key_sha256=TEST_HOST_KEY_SHA256,
                port=22,
            )

        self.assertFalse(result)

    def test_reboot_device_via_ssh_adb_allows_stderr_when_exit_status_is_zero(self):
        with patch.object(
            ssh_control,
            "exec_cmd_by_ssh_with_status",
            return_value=("", "adb warning", 0),
        ):
            result = ssh_control.reboot_device_via_ssh_adb(
                device_ip="127.0.0.1",
                username="user",
                password="pass",
                device_serial="device-1",
                host_key_sha256=TEST_HOST_KEY_SHA256,
                port=22,
            )

        self.assertTrue(result)

    def test_choose_adb_serial_prefers_explicit_adb_serial(self):
        config = {"device_name": "appium-name", "adb_serial": "real-adb-serial"}

        result = zacks_reboot.choose_adb_serial(config, ["real-adb-serial"])

        self.assertEqual(result, "real-adb-serial")

    def test_choose_adb_serial_falls_back_to_only_online_device(self):
        config = {"device_name": "appium-name"}

        result = zacks_reboot.choose_adb_serial(config, ["tcp:5555"])

        self.assertEqual(result, "tcp:5555")

    def test_choose_adb_serial_raises_when_multiple_devices_do_not_match(self):
        config = {"device_name": "appium-name"}

        with self.assertRaises(ValueError):
            zacks_reboot.choose_adb_serial(config, ["device-a", "device-b"])
