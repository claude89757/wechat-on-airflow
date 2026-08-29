from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import _ops  # noqa: E402
import airflow_db_cleanup  # noqa: E402
import capture_wechat_sender_ui  # noqa: E402
import deploy_airflow  # noqa: E402
import deploy_wechat_sender  # noqa: E402
import diagnose_wechat_delivery  # noqa: E402
import diagnose_zacks_phone  # noqa: E402
import github_release_gate  # noqa: E402
import prepare_fresh_start_config  # noqa: E402
import probe_wechat_delivery  # noqa: E402
import production_health  # noqa: E402
import quiesce_wechat_delivery  # noqa: E402
import resume_airflow_scheduling  # noqa: E402
import sync_nswtt_config  # noqa: E402
import sync_pi_device_ssh  # noqa: E402
import verify_fresh_start_config  # noqa: E402
import webapp_production_health  # noqa: E402


class RemoteSshAuthenticationContractTest(unittest.TestCase):
    def test_remote_operations_require_public_key_authentication(self):
        for script_name in (
            "airflow_db_cleanup.py",
            "diagnose_zacks_phone.py",
            "deploy_airflow.py",
            "deploy_wechat_sender.py",
            "diagnose_wechat_delivery.py",
            "probe_wechat_delivery.py",
            "production_health.py",
            "quiesce_wechat_delivery.py",
            "resume_airflow_scheduling.py",
            "sync_nswtt_config.py",
            "sync_pi_device_ssh.py",
        ):
            source = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
            self.assertNotIn("sshpass", source, script_name)
            self.assertNotIn('remote["PASSWORD"]', source, script_name)

        command = _ops.ssh_command({"host": "host", "port": "22", "username": "deploy"})
        self.assertIn("PreferredAuthentications=publickey", command)
        self.assertIn("PasswordAuthentication=no", command)
        self.assertIn("ServerAliveInterval=30", command)
        self.assertIn("ServerAliveCountMax=20", command)


class NswttConfigSyncTest(unittest.TestCase):
    def test_sync_contract_accepts_only_bounded_fields(self):
        value = sync_nswtt_config.validated_config(
            '{"app_version":"2.14.30","cookie":{"sid":"secret"}}'
        )
        self.assertIn('"app_version":"2.14.30"', value)

        with self.assertRaisesRegex(_ops.OpsError, "unsupported fields"):
            sync_nswtt_config.validated_config(
                '{"app_version":"2.14.30","cookie":"sid=x","email":"hidden"}'
            )


class PiDeviceSshSyncTest(unittest.TestCase):
    def test_sync_contract_requires_complete_ssh_fields(self):
        value = sync_pi_device_ssh.validated_config(
            {
                "host": "203.0.113.10",
                "port": "6000",
                "username": "pi-user",
                "password": "secret",
                "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            }
        )
        parsed = json.loads(value)
        self.assertEqual(parsed["port"], 6000)
        self.assertEqual(parsed["host"], "203.0.113.10")

        with self.assertRaisesRegex(_ops.OpsError, "missing required SSH fields"):
            sync_pi_device_ssh.validated_config({"host": "203.0.113.10", "port": "6000"})
        with self.assertRaisesRegex(_ops.OpsError, "must be an integer"):
            sync_pi_device_ssh.validated_config(
                {
                    "host": "203.0.113.10",
                    "port": "not-a-port",
                    "username": "pi-user",
                    "password": "secret",
                    "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                }
            )

        source = (ROOT / "scripts" / "sync_pi_device_ssh.py").read_text(encoding="utf-8")
        self.assertIn("sorted(value.keys())", source)
        self.assertNotIn("print(config_json)", source)
        self.assertNotIn("print(raw_fields", source)


class AirflowSchedulingResumeTest(unittest.TestCase):
    def test_resume_is_bounded_to_declared_dags_without_triggering_runs(self):
        script = resume_airflow_scheduling.remote_script()

        self.assertIn("airflow dags unpause", script)
        self.assertIn("--treat-dag-id-as-regex --yes", script)
        self.assertIn('verification["paused_dags"] == 0', script)
        self.assertIn('"missing_required_services": missing_required_services', script)
        self.assertIn('"unpause_command_exit_code": unpause_exit_code', script)
        self.assertNotIn("service_count == 9", script)
        self.assertNotIn("airflow dags trigger", script)
        self.assertNotIn("DagRun", script)


class WeChatDeliveryDiagnosisTest(unittest.TestCase):
    def test_diagnosis_is_read_only_and_redacts_receiver_and_message(self):
        script = diagnose_wechat_delivery.remote_script()

        self.assertIn('"target_index": target_index', script)
        self.assertIn('"error_category": category', script)
        self.assertIn('"chat_title_not_verified"', script)
        self.assertIn('"search_result_did_not_open"', script)
        self.assertIn('"search_return_failed"', script)
        self.assertNotIn('"receiver":', script)
        self.assertNotIn('"message":', script)
        self.assertNotIn("Variable.set", script)
        self.assertNotIn("Variable.delete", script)


class WeChatDeliveryProbeTest(unittest.TestCase):
    def test_probe_requires_approval_and_redacts_targets_and_message(self):
        script = probe_wechat_delivery.remote_script()

        self.assertIn('test "$2" = "real-send-approved"', script)
        self.assertIn("PROBE_TARGET_MEMBERSHIP=$3", script)
        self.assertIn('if selector == "all":', script)
        self.assertIn('"dsh_free": ["Zacks_大沙河限定免费"]', script)
        self.assertIsNotNone(
            probe_wechat_delivery.TARGET_MEMBERSHIP_PATTERN.fullmatch("dsh_free:1")
        )
        self.assertIsNone(probe_wechat_delivery.TARGET_MEMBERSHIP_PATTERN.fullmatch("other:1"))
        self.assertIn('"target_selector": selector or None', script)
        self.assertIn('"real_send": True', script)
        self.assertIn('"lane_start_spread_ms": start_spread_ms', script)
        self.assertIn('"memberships": target["memberships"]', script)
        self.assertIn('"navigation_path": payload.get("navigation_path", "unknown")', script)
        self.assertNotIn('"receiver": target["receiver"]', script.split("print(")[-1])
        self.assertNotIn('"message": message', script.split("print(")[-1])
        self.assertNotIn("Variable.set", script)
        self.assertNotIn("WECHAT_SEND_FALLBACK_OUTBOX", script)


class WeChatSenderServiceContractTest(unittest.TestCase):
    def test_systemd_service_runs_one_unprivileged_restartable_worker(self):
        unit = (ROOT / "deploy/systemd/wechat-sender.service").read_text(encoding="utf-8")

        self.assertIn("User=wechat-sender", unit)
        self.assertIn("LoadCredential=wechat_allowed_device_name:", unit)
        self.assertIn("LoadCredential=wechat_appium_url:", unit)
        self.assertNotIn("EnvironmentFile=", unit)
        self.assertIn(
            "ExecStart=/opt/wechat-sender-venv/bin/python -m uvicorn ",
            unit,
        )
        self.assertIn("--port 7001 --workers 1", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("Requires=appium-6002.service", unit)
        self.assertNotIn("PrivateDevices=true", unit)

        override = (ROOT / "deploy/systemd/appium-6002.override.conf").read_text(encoding="utf-8")
        self.assertIn("--address 127.0.0.1", override)
        self.assertIn("--session-override", override)
        self.assertIn("--log-level warn", override)
        self.assertIn("ExecStartPre=/usr/bin/adb start-server", override)
        self.assertIn("Restart=always", override)

    def test_installer_is_read_only_by_default_and_requires_exact_commit(self):
        installer = (ROOT / "scripts/install_wechat_sender.sh").read_text(encoding="utf-8")

        self.assertIn("APPLY=false", installer)
        self.assertIn('[[ "$APPLY" != true ]]', installer)
        self.assertIn("^[0-9a-f]{40}$", installer)
        self.assertIn('checkout --detach "$TARGET_COMMIT"', installer)
        self.assertIn("Git fetch failed after 3 attempts", installer)
        self.assertIn(
            'if ! git -C "$INSTALL_DIR" cat-file -e "${TARGET_COMMIT}^{commit}"',
            installer,
        )
        self.assertIn("systemctl enable", installer)
        self.assertIn("http://127.0.0.1:7001/readyz", installer)
        self.assertIn("tesseract --list-langs", installer)
        self.assertIn("python3-pil with Image.Resampling support is required", installer)
        self.assertIn("python3 -m venv --system-site-packages", installer)
        self.assertIn("grep -v '^Pillow=='", installer)
        self.assertIn('adb -s "$DEVICE_NAME" get-state', installer)
        self.assertIn("appium-6002.override.conf", installer)


class DockerComposeCommandTest(unittest.TestCase):
    def test_airflow_api_server_is_proxy_aware_and_loopback_only(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        api_server = compose["services"]["airflow-api-server"]

        self.assertIn("--proxy-headers", api_server["command"])
        self.assertEqual(api_server["ports"], ["127.0.0.1:8080:8080"])

    def test_runtime_uses_file_backed_secrets(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        runtime = yaml.safe_load((ROOT / "config/runtime-target.yaml").read_text(encoding="utf-8"))
        environment = compose["x-airflow-env"]

        self.assertIn("AIRFLOW__CORE__FERNET_KEY_CMD", environment)
        self.assertIn("AIRFLOW__DATABASE__SQL_ALCHEMY_CONN_CMD", environment)
        self.assertIn("read_runtime_secret.py", environment["AIRFLOW__CORE__FERNET_KEY_CMD"])
        self.assertNotIn("AIRFLOW__CORE__FERNET_KEY", environment)
        self.assertEqual(len(compose["secrets"]), 5)
        self.assertFalse((ROOT / ".env.example").exists())
        self.assertEqual(runtime["target"]["local_secret_file_mode"], "0644")
        self.assertEqual(runtime["target"]["production_secret_file_mode"], "0640")

    @patch("_ops.subprocess.run")
    @patch("_ops.shutil.which")
    def test_prefers_docker_compose_plugin(self, mock_which, mock_run):
        mock_which.side_effect = lambda command: {
            "docker": "/usr/local/bin/docker",
            "docker-compose": "/usr/local/bin/docker-compose",
        }.get(command)
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")

        self.assertEqual(
            _ops.docker_compose_command(),
            ["/usr/local/bin/docker", "compose"],
        )

    @patch("_ops.subprocess.run")
    @patch("_ops.shutil.which")
    def test_falls_back_to_legacy_docker_compose(self, mock_which, mock_run):
        mock_which.side_effect = lambda command: {
            "docker": "/usr/local/bin/docker",
            "docker-compose": "/usr/local/bin/docker-compose",
        }.get(command)
        mock_run.return_value = subprocess.CompletedProcess([], 1, "", "not installed")

        self.assertEqual(
            _ops.docker_compose_command(),
            ["/usr/local/bin/docker-compose"],
        )


class AirflowDeploymentTest(unittest.TestCase):
    def test_image_name_is_derived_from_exact_commit(self):
        commit = "a" * 40

        self.assertEqual(
            deploy_airflow.airflow_image_name("3.3.0", commit),
            "wechat-on-airflow:3.3.0-aaaaaaa",
        )

    def test_image_name_rejects_non_exact_commit(self):
        with self.assertRaises(_ops.OpsError):
            deploy_airflow.airflow_image_name("3.3.0", "main")

    def test_remote_result_parser_ignores_non_structured_output(self):
        output = 'build output\n{"ok": true, "applied": false}\n'

        self.assertEqual(
            deploy_airflow.parse_remote_result(output),
            {"ok": True, "applied": False},
        )

    def test_application_deploy_never_targets_stateful_services(self):
        self.assertNotIn("postgresql", deploy_airflow.APPLICATION_SERVICES)
        self.assertNotIn("redis", deploy_airflow.APPLICATION_SERVICES)

    def test_application_deploy_drains_tasks_and_restores_dag_state(self):
        script = deploy_airflow.remote_script()

        self.assertIn("active_task_count", script)
        self.assertIn("airflow dags pause", script)
        self.assertIn("airflow dags unpause", script)
        self.assertIn("--treat-dag-id-as-regex --yes", script)
        self.assertIn("restore_dags", script)
        self.assertIn("active task instances did not drain", script)
        self.assertIn("target_dag_ids_b64", script)
        self.assertIn("retired_dags_left_paused", script)
        self.assertIn('restore_dags "$restore_regex"', script)
        self.assertIn("if dag_id not in current_set:", script)
        self.assertIn("states.get(dag_id, False)", script)
        self.assertIn("states.get(dag_id, True)", script)

    def test_newly_introduced_target_dags_are_restored_unpaused(self):
        current = {"existing"}

        self.assertFalse(
            deploy_airflow.planned_target_pause_state(
                "new_venue",
                current_dag_ids=current,
                recorded_paused=True,
            )
        )
        self.assertFalse(
            deploy_airflow.planned_target_pause_state(
                "new_venue",
                current_dag_ids=current,
                recorded_paused=None,
            )
        )
        self.assertTrue(
            deploy_airflow.planned_target_pause_state(
                "existing",
                current_dag_ids=current,
                recorded_paused=True,
            )
        )
        self.assertFalse(
            deploy_airflow.planned_target_pause_state(
                "existing",
                current_dag_ids=current,
                recorded_paused=False,
            )
        )

    def test_recovery_deploy_bounds_current_work_and_preserves_outbox(self):
        script = deploy_airflow.remote_script()

        self.assertIn('if [ "$recover_active_tasks" = "true" ]', script)
        self.assertIn(
            "compose stop -t 15 airflow-scheduler airflow-worker airflow-triggerer </dev/null",
            script,
        )
        self.assertIn(
            '[ "$rc" -ne 0 ] || [ "$execution_services_stopped" = "true" ]',
            script,
        )
        self.assertIn("TaskInstance.dag_id.in_(dag_ids)", script)
        self.assertIn("DagRun.dag_id.in_(dag_ids)", script)
        self.assertIn('task_instance.state = "failed"', script)
        self.assertIn('dag_run.state = "failed"', script)
        self.assertIn("redis-cli FLUSHDB", script)
        self.assertIn('"outbox_preserved": True', script)
        self.assertNotIn("Variable.delete", script)

    def test_application_deploy_requires_file_secrets_without_exporting_values(self):
        script = deploy_airflow.remote_script()

        self.assertIn("validate_runtime_secrets", script)
        self.assertIn("640:0:0", script)
        self.assertNotIn("migrate_runtime_secrets", script)
        self.assertNotIn("AIRFLOW_FERNET_KEY=", script)
        self.assertNotIn("rollback_env_file", script)
        self.assertIn("compose build --quiet airflow-api-server </dev/null", script)


class WeChatSenderDeploymentTest(unittest.TestCase):
    def test_sender_deploy_is_exact_commit_and_requires_systemd_credentials(self):
        script = deploy_wechat_sender.remote_script()

        self.assertIn('cat-file -e "$target_commit^{commit}"', script)
        self.assertIn('fetch --quiet --force "$bundle_path"', script)
        self.assertIn("refs/remotes/origin/main:refs/remotes/origin/main", script)
        self.assertNotIn("fetch --quiet origin", script)
        self.assertIn('rm -f -- "$bundle_path"', script)
        self.assertIn("wechat_allowed_device_name", script)
        self.assertIn("rollback", script)
        self.assertNotIn("wechat-sender.env", script)
        self.assertNotIn("legacy_migration", script)
        self.assertIn(
            'install_wechat_sender.sh" --apply --target-commit "$target_commit" </dev/null', script
        )

    @patch("deploy_wechat_sender.run")
    def test_sender_bundle_upload_uses_hardened_scp(self, mock_run):
        deploy_wechat_sender.upload_deployment_bundle(
            ROOT / "repository.bundle",
            {"host": "sender.example", "port": "6000", "username": "deployer"},
            "/tmp/wechat-sender-test.bundle",
        )

        command = mock_run.call_args.args[0]
        self.assertEqual(command[0], "scp")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=yes", command)
        self.assertEqual(command[-1], "deployer@sender.example:/tmp/wechat-sender-test.bundle")

    def test_sender_device_recovery_is_bounded_and_never_reboots_or_sends(self):
        script = deploy_wechat_sender.remote_script()

        self.assertIn('if [ "$mode" = "device-diagnose" ]', script)
        self.assertIn('if [ "$mode" = "device-recover" ]', script)
        self.assertIn("adb kill-server", script)
        self.assertIn("adb start-server", script)
        self.assertIn("usb_adb_interface_count", script)
        self.assertIn('"phone_rebooted": False', script)
        self.assertIn('"notification_sent": False', script)
        self.assertNotIn("adb reboot", script)
        self.assertNotIn("/v1/wechat/send", script)

    def test_sender_device_diagnosis_captures_only_sanitized_ui_structure(self):
        script = deploy_wechat_sender.remote_script()

        self.assertIn("uiautomator dump --compressed", script)
        self.assertIn('exec-out cat "$remote_ui_dump"', script)
        self.assertIn('"top_clickable_controls": []', script)
        self.assertIn('"search_controls": []', script)
        self.assertIn('"edit_inputs": []', script)
        self.assertIn('"has_text": bool(attributes.get("text"))', script)
        self.assertNotIn('"text": attributes.get("text")', script)
        self.assertNotIn('"content_description": attributes.get("content-desc")', script)

    def test_sender_ui_capture_is_read_only_and_never_logs_image_bytes(self):
        script = capture_wechat_sender_ui.remote_script()

        self.assertIn("exec-out screencap -p", script)
        self.assertNotIn("input tap", script)
        self.assertNotIn("click", script)
        self.assertNotIn("/v1/wechat/send", script)
        self.assertNotIn("uiautomator", script)

    @patch("capture_wechat_sender_ui.sender_remote")
    @patch("capture_wechat_sender_ui.subprocess.run")
    def test_sender_ui_capture_validates_png_before_writing(self, mock_run, mock_remote):
        mock_remote.return_value = {
            "host": "sender.example",
            "port": "6000",
            "username": "deployer",
        }
        png = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00" * 8
            + (1080).to_bytes(4, "big")
            + (2340).to_bytes(4, "big")
        )
        mock_run.return_value = subprocess.CompletedProcess([], 0, png, b"")

        with self.subTest("valid PNG"):
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as directory:
                output = Path(directory) / "wechat-ui.png"
                self.assertEqual(
                    capture_wechat_sender_ui.capture_screenshot(output),
                    (1080, 2340),
                )
                self.assertEqual(output.read_bytes(), png)


class WeChatDeliveryQuiesceTest(unittest.TestCase):
    def test_quiesce_is_scoped_and_preserves_incident_outbox(self):
        script = quiesce_wechat_delivery.remote_script()

        self.assertEqual(len(quiesce_wechat_delivery.WECHAT_DAG_IDS), 14)
        self.assertIn("大沙河国际网球中心巡检", quiesce_wechat_delivery.WECHAT_DAG_IDS)
        self.assertIn("泛思博特深云网球场巡检", quiesce_wechat_delivery.WECHAT_DAG_IDS)
        self.assertIn("PICKLEPOP宝安网球场巡检", quiesce_wechat_delivery.WECHAT_DAG_IDS)
        self.assertIn("expected_paused = 14", script)
        self.assertIn(
            "compose stop -t 15 airflow-scheduler airflow-worker airflow-triggerer",
            script,
        )
        self.assertIn("model.is_paused = True", script)
        self.assertIn('task_instance.state = "failed"', script)
        self.assertIn('dag_run.state = "failed"', script)
        self.assertIn("redis-cli FLUSHDB", script)
        self.assertIn('"purged_broker_keys": int(sys.argv[3])', script)
        self.assertIn('"operation_commit": sys.argv[2]', script)
        self.assertIn('"outbox_preserved": True', script)
        self.assertIn('health="$(docker inspect', script)
        self.assertNotIn("Variable.delete", script)
        self.assertNotIn("WECHAT_SEND_FALLBACK_OUTBOX_VAR", script)

        verification = quiesce_wechat_delivery.verification_script()
        self.assertIn('"active_wechat_task_instances"', verification)
        self.assertIn('"active_wechat_dag_runs"', verification)

    def test_quiesce_remote_result_parser_uses_structured_output(self):
        self.assertEqual(
            quiesce_wechat_delivery.parse_remote_result(
                'progress\n{"ok": true, "cleared_task_instances": 4}\n'
            ),
            {"ok": True, "cleared_task_instances": 4},
        )

    def test_quiesce_requires_paused_dags_and_no_active_work(self):
        quiet = {
            "paused_wechat_dags": 14,
            "active_wechat_task_instances": 0,
            "active_wechat_dag_runs": 0,
        }

        self.assertTrue(quiesce_wechat_delivery.is_quiesced(quiet))
        self.assertFalse(
            quiesce_wechat_delivery.is_quiesced({**quiet, "active_wechat_task_instances": 1})
        )

    def test_production_health_reports_runtime_secret_metadata_without_values(self):
        source = (SCRIPTS_DIR / "production_health.py").read_text(encoding="utf-8")

        self.assertIn('"runtime_secrets"', source)
        self.assertNotIn("(directory / name).read_text", source)
        self.assertNotIn("(directory / name).read_bytes", source)


class AirflowDatabaseCleanupTest(unittest.TestCase):
    def test_default_command_is_read_only(self):
        cutoff = datetime(2026, 1, 1, tzinfo=UTC)

        command = airflow_db_cleanup.cleanup_command(cutoff, apply=False)

        self.assertIn("--dry-run", command)
        self.assertNotIn("--yes", command)
        self.assertNotIn("--skip-archive", command)

    def test_apply_command_requires_explicit_destructive_flags(self):
        cutoff = datetime(2026, 1, 1, tzinfo=UTC)

        command = airflow_db_cleanup.cleanup_command(cutoff, apply=True)

        self.assertIn("--yes", command)
        self.assertIn("--skip-archive", command)
        self.assertIn("--error-on-cleanup-failure", command)

    def test_confirmed_cutoff_is_utc_midnight(self):
        self.assertEqual(
            airflow_db_cleanup.confirmed_cutoff("2026-01-02"),
            datetime(2026, 1, 2, tzinfo=UTC),
        )

    def test_remote_result_parser_uses_structured_tail(self):
        self.assertEqual(
            airflow_db_cleanup.parse_remote_result(
                'command output\n{"ok": true, "mode": "dry-run"}\n'
            ),
            {"ok": True, "mode": "dry-run"},
        )

    def test_remote_cleanup_commands_cannot_consume_the_control_script(self):
        script = airflow_db_cleanup.remote_script()

        self.assertEqual(script.count("</dev/null >/dev/null"), 2)


class ProductionHealthParsingTest(unittest.TestCase):
    def test_airflow3_active_dag_probe_uses_is_stale_column(self):
        source = (SCRIPTS_DIR / "production_health.py").read_text(encoding="utf-8")

        self.assertIn("DagModel.is_stale", source)
        self.assertNotIn("DagModel.is_active", source)

    def test_remote_ingress_probe_supports_host_python_36(self):
        source = (SCRIPTS_DIR / "production_health.py").read_text(encoding="utf-8")

        self.assertIn("universal_newlines=True", source)
        self.assertIn("wechat-on-airflow-production-health/1.0", source)
        self.assertNotIn("capture_output=True", source)

    def test_notification_health_uses_contract_declared_outboxes(self):
        source = (SCRIPTS_DIR / "production_health.py").read_text(encoding="utf-8")

        self.assertIn("__FALLBACK_OUTBOX_NAMES_JSON__", source)
        self.assertNotIn(
            'for key in ("EMAIL_SEND_FALLBACK_OUTBOX", "WECHAT_SEND_FALLBACK_OUTBOX")',
            source,
        )

    def test_parse_sections_separates_remote_command_output(self):
        output = "\n".join(
            [
                "__COMMIT__",
                "abc123",
                "__AIRFLOW_VERSION__",
                "3.3.0",
                "__EXECUTION_API__",
                '{"ok": true, "status_code": 401}',
                "__DAG_SOURCES__",
                '{"expected_count": 9, "missing": [], "unreadable": []}',
                "__OUTBOXES__",
                '{"WECHAT_SEND_FALLBACK_OUTBOX": 0}',
                "__DATABASE__",
                '{"database_bytes": 1024}',
                "__STORAGE__",
                '{"free_bytes": 2048}',
                "__MANAGED_SERVICES__",
                '{"wechat_sender": {"ok": true}}',
                "__INGRESS__",
                '{"ok": true, "service_active": true}',
            ]
        )

        sections = production_health.parse_sections(output)

        self.assertEqual(sections["commit"], "abc123")
        self.assertEqual(sections["airflow_version"], "3.3.0")
        self.assertEqual(
            production_health.parse_json_output(sections["execution_api"], {}),
            {"ok": True, "status_code": 401},
        )
        self.assertEqual(
            production_health.parse_json_output(sections["dag_sources"], {}),
            {"expected_count": 9, "missing": [], "unreadable": []},
        )
        self.assertEqual(
            production_health.parse_json_output(sections["outboxes"], {}),
            {"WECHAT_SEND_FALLBACK_OUTBOX": 0},
        )
        self.assertEqual(
            production_health.parse_json_output(sections["database"], {}),
            {"database_bytes": 1024},
        )
        self.assertEqual(
            production_health.parse_json_output(sections["storage"], {}),
            {"free_bytes": 2048},
        )
        self.assertEqual(
            production_health.parse_json_output(sections["managed_services"], {}),
            {"wechat_sender": {"ok": True}},
        )
        self.assertEqual(
            production_health.parse_json_output(sections["ingress"], {}),
            {"ok": True, "service_active": True},
        )

    def test_parse_compose_rows_supports_line_delimited_json(self):
        output = "\n".join(
            [
                '{"Service":"scheduler","State":"running"}',
                '{"Service":"worker","State":"running"}',
            ]
        )

        rows = production_health.parse_compose_rows(output)

        self.assertEqual([row["Service"] for row in rows], ["scheduler", "worker"])

    def test_parse_compose_rows_supports_json_array(self):
        output = (
            "warning before output\n"
            '[{"Service":"airflow-api-server","State":"running"},'
            '{"Service":"airflow-worker","State":"running"}]'
        )

        rows = production_health.parse_compose_rows(output)

        self.assertEqual(
            [row["Service"] for row in rows],
            ["airflow-api-server", "airflow-worker"],
        )

    def test_normalized_bool_accepts_cli_boolean_values(self):
        self.assertTrue(production_health.normalized_bool(True))
        self.assertTrue(production_health.normalized_bool("True"))
        self.assertFalse(production_health.normalized_bool("False"))

    def test_run_history_requirements_follow_each_dag_contract(self):
        counts = production_health.required_successful_run_counts(
            [
                {
                    "dag_id": "venue",
                    "verification": ["dag_imports", "recent_runs_succeed"],
                },
                {
                    "dag_id": "proxy",
                    "verification": ["dag_imports", "latest_run_succeeds"],
                },
                {
                    "dag_id": "import_only",
                    "verification": ["dag_imports"],
                },
            ],
            production_cycles=3,
        )

        self.assertEqual(counts, {"venue": 3, "proxy": 1, "import_only": 0})

    def test_new_dag_without_run_history_is_not_an_apply_failure(self):
        no_history, is_new = production_health.classify_recent_run_history(3, [])
        self.assertIsNone(no_history)
        self.assertTrue(is_new)

        partial_success, still_new = production_health.classify_recent_run_history(
            3, [{"state": "success"}]
        )
        self.assertIsNone(partial_success)
        self.assertTrue(still_new)

        two_successes, still_warming = production_health.classify_recent_run_history(
            3, [{"state": "success"}, {"state": "success"}]
        )
        self.assertIsNone(two_successes)
        self.assertTrue(still_warming)

        failed, _ = production_health.classify_recent_run_history(
            3, [{"state": "failed"}, {"state": "success"}]
        )
        self.assertEqual(
            failed, {"observed_count": 2, "required_count": 3, "states": ["failed", "success"]}
        )

        healthy, _ = production_health.classify_recent_run_history(
            3,
            [{"state": "success"}, {"state": "success"}, {"state": "success"}],
        )
        self.assertIsNone(healthy)

    def test_deployment_commit_must_match_exact_release_commit(self):
        commit = "a" * 40

        self.assertTrue(production_health.deployment_commit_matches(commit, commit))
        self.assertFalse(production_health.deployment_commit_matches(commit, "b" * 40))
        self.assertFalse(production_health.deployment_commit_matches("main", "main"))

    def test_production_health_does_not_derive_expected_commit_from_local_head(self):
        source = (SCRIPTS_DIR / "production_health.py").read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--expected-commit", required=True)', source)
        self.assertNotIn('run(["git", "rev-parse", "HEAD"])', source)

    def test_fallback_outboxes_distinguish_recent_and_historical_failures(self):
        now = datetime(2026, 7, 19, 1, 0, tzinfo=UTC)
        outboxes = {
            "RECENT": {"count": 2, "latest_failed_at": "2026-07-19T00:50:00+00:00"},
            "HISTORICAL": {"count": 4, "latest_failed_at": "2026-07-18T12:00:00+00:00"},
            "EMPTY": {"count": 0, "latest_failed_at": None},
        }

        recent, historical, malformed = production_health.classify_fallback_outboxes(
            outboxes,
            now=now,
            grace_minutes=30,
        )

        self.assertEqual(set(recent), {"RECENT"})
        self.assertEqual(set(historical), {"HISTORICAL"})
        self.assertEqual(malformed, {})

    def test_fallback_outboxes_reject_malformed_nonempty_records(self):
        recent, historical, malformed = production_health.classify_fallback_outboxes(
            {"BROKEN": {"count": 1, "latest_failed_at": None}},
            now=datetime(2026, 7, 19, 1, 0, tzinfo=UTC),
            grace_minutes=30,
        )

        self.assertEqual(recent, {})
        self.assertEqual(historical, {})
        self.assertEqual(set(malformed), {"BROKEN"})


class PhoneDiagnosticTest(unittest.TestCase):
    def test_diagnostic_is_read_only_and_scoped_to_zacks_reboot(self):
        script = diagnose_zacks_phone.remote_script()

        self.assertIn('DAG_ID = "zacks_phone_daily_reboot"', script)
        self.assertIn('"read_only": True', script)
        self.assertIn("error_signatures", script)
        self.assertIn('build_login_shell_adb_command("devices")', script)
        self.assertIn('"failure_category": None', script)
        self.assertIn('Variable.get("APPIUM_SERVER_LIST"', script)
        self.assertIn("ANDROID_DEVICE_LOGGER.disabled = True", script)
        self.assertNotIn("reboot_device", script)
        self.assertNotIn('build_login_shell_adb_command("reboot")', script)

    def test_diagnostic_parses_only_structured_result(self):
        payload = diagnose_zacks_phone.parse_remote_result(
            'command output\n{"ok": true, "read_only": true}\n'
        )

        self.assertEqual(payload, {"ok": True, "read_only": True})

    def test_embedded_diagnostic_python_is_valid(self):
        script = diagnose_zacks_phone.remote_script()
        python_source = script.split("python - <<'PY'\n", 1)[1].rsplit("\nPY\n", 1)[0]

        compile(python_source, "diagnose_zacks_phone_remote.py", "exec")

    def test_diagnostic_redacts_credentials_from_error_evidence(self):
        value = "postgresql://user:pass@db password=unsafe"

        redacted = diagnose_zacks_phone.redact_error(value)

        self.assertNotIn(":pass@", redacted)
        self.assertNotIn("unsafe", redacted)
        self.assertIn("<redacted>", redacted)


class FreshStartConfigurationTest(unittest.TestCase):
    def test_preserves_static_and_continuity_values_but_resets_outbox(self):
        exported = {
            "STATIC": "secret-value",
            "CACHE": '["seen"]',
            "OUTBOX": '[{"error":"old"}]',
            "OBSOLETE": "ignored",
        }
        contracts = {
            "variables": {
                "STATIC": {
                    "type": "string",
                    "required_by": ["owner"],
                    "sensitive": True,
                },
                "CACHE": {
                    "type": "json_list",
                    "required_by": ["owner"],
                    "sensitive": False,
                    "managed_by_application": True,
                    "fresh_start_policy": "preserve",
                },
                "OUTBOX": {
                    "type": "json_list",
                    "required_by": ["owner"],
                    "sensitive": True,
                    "managed_by_application": True,
                    "fresh_start_policy": "reset",
                },
                "RETRY_COUNT": {
                    "type": "positive_integer",
                    "required_by": ["owner"],
                    "sensitive": False,
                    "default": 3,
                },
            }
        }

        prepared, report = prepare_fresh_start_config.prepare_variables(exported, contracts)

        self.assertTrue(report["ok"])
        self.assertEqual(
            prepared,
            {
                "CACHE": '["seen"]',
                "OUTBOX": "[]",
                "RETRY_COUNT": "3",
                "STATIC": "secret-value",
            },
        )
        self.assertEqual(report["ignored_count"], 1)
        self.assertNotIn("secret-value", str(report))

    def test_missing_required_preserved_value_fails_closed(self):
        prepared, report = prepare_fresh_start_config.prepare_variables(
            {},
            {
                "variables": {
                    "REQUIRED": {
                        "type": "string",
                        "required_by": ["owner"],
                        "sensitive": True,
                    }
                }
            },
        )

        self.assertEqual(prepared, {})
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing_names"], ["REQUIRED"])

    def test_verification_reports_names_without_values(self):
        expected = {"A": "secret-a", "B": "secret-b", "C": "secret-c"}
        actual = {"A": "secret-a", "B": "wrong"}

        def getter(name):
            if name not in actual:
                raise KeyError(name)
            return actual[name]

        report = verify_fresh_start_config.compare_variables(expected, getter)

        self.assertFalse(report["ok"])
        self.assertEqual(report["missing_names"], ["C"])
        self.assertEqual(report["mismatched_names"], ["B"])
        self.assertNotIn("secret", str(report))


class GithubOnlyDeliveryContractTest(unittest.TestCase):
    def test_release_gate_uses_latest_required_check_run(self):
        result = github_release_gate.required_check_result(
            {
                "check_runs": [
                    {
                        "id": 10,
                        "name": "verify",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "id": 11,
                        "name": "verify",
                        "status": "completed",
                        "conclusion": "failure",
                    },
                ]
            },
            "verify",
        )

        self.assertTrue(result["present"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["conclusion"], "failure")

    def test_release_gate_rejects_a_missing_required_check(self):
        result = github_release_gate.required_check_result({"check_runs": []}, "verify")

        self.assertEqual(
            result,
            {"present": False, "status": None, "conclusion": None, "ok": False},
        )

    def test_webapp_health_detects_public_email_leakage(self):
        self.assertTrue(
            webapp_production_health.contains_email(
                {"nested": [{"recipient": "person@example.com"}]}
            )
        )
        self.assertFalse(
            webapp_production_health.contains_email({"nested": [{"masked": "pe****@example.com"}]})
        )

    def test_webapp_health_retries_only_during_commit_propagation(self):
        healthy_checks = {
            "health_http_ok": True,
            "service_healthy": True,
            "exact_deployment_commit": False,
            "bootstrap_http_ok": True,
            "expected_venue_count": True,
            "bootstrap_contains_no_email": True,
            "observation_requires_authentication": True,
        }

        self.assertTrue(
            webapp_production_health.deployment_is_propagating({"checks": healthy_checks})
        )
        self.assertFalse(
            webapp_production_health.deployment_is_propagating(
                {"checks": {**healthy_checks, "bootstrap_http_ok": False}}
            )
        )
        self.assertFalse(
            webapp_production_health.deployment_is_propagating(
                {"checks": {**healthy_checks, "exact_deployment_commit": True}}
            )
        )

        stale = {"ok": False, "checks": healthy_checks}
        ready = {
            "ok": True,
            "checks": {**healthy_checks, "exact_deployment_commit": True},
        }
        with (
            patch.object(
                webapp_production_health,
                "inspect_production",
                side_effect=[stale, ready],
            ) as inspect,
            patch.object(
                webapp_production_health.time,
                "monotonic",
                side_effect=[0, 1],
            ),
            patch.object(webapp_production_health.time, "sleep") as sleep,
        ):
            result = webapp_production_health.wait_for_production(
                base_url="https://example.invalid",
                expected_commit="a" * 40,
                expected_venue_count=7,
                propagation_timeout_seconds=10,
                retry_interval_seconds=5,
            )

        self.assertIs(result, ready)
        self.assertEqual(inspect.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_application_preflights_do_not_require_local_database_backups(self):
        for name in ("deploy_check.py", "rollback_check.py"):
            source = (SCRIPTS_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn("airflow-production-backups", source, name)
            self.assertNotIn("latest_successful_backup", source, name)


if __name__ == "__main__":
    unittest.main()
