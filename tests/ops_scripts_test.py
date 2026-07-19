from __future__ import annotations

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
import deploy_airflow  # noqa: E402
import prepare_fresh_start_config  # noqa: E402
import production_health  # noqa: E402
import verify_fresh_start_config  # noqa: E402


class WeChatSenderServiceContractTest(unittest.TestCase):
    def test_systemd_service_runs_one_unprivileged_restartable_worker(self):
        unit = (ROOT / "deploy/systemd/wechat-sender.service").read_text(encoding="utf-8")

        self.assertIn("User=wechat-sender", unit)
        self.assertIn("EnvironmentFile=/etc/wechat-sender.env", unit)
        self.assertIn(
            "ExecStart=/opt/wechat-sender-venv/bin/python -m uvicorn ",
            unit,
        )
        self.assertIn("--port 7001 --workers 1", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("Requires=appium-6002.service", unit)

    def test_installer_is_read_only_by_default_and_requires_exact_commit(self):
        installer = (ROOT / "scripts/install_wechat_sender.sh").read_text(encoding="utf-8")

        self.assertIn("APPLY=false", installer)
        self.assertIn('[[ "$APPLY" != true ]]', installer)
        self.assertIn("^[0-9a-f]{40}$", installer)
        self.assertIn('checkout --detach "$TARGET_COMMIT"', installer)
        self.assertIn("Git fetch failed after 3 attempts", installer)
        self.assertIn("systemctl enable", installer)
        self.assertIn("http://127.0.0.1:7001/readyz", installer)


class DockerComposeCommandTest(unittest.TestCase):
    def test_airflow_api_server_is_proxy_aware_and_loopback_only(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        api_server = compose["services"]["airflow-api-server"]

        self.assertIn("--proxy-headers", api_server["command"])
        self.assertEqual(api_server["ports"], ["127.0.0.1:8080:8080"])

    def test_example_urls_preserve_airflow_path_prefix(self):
        env_lines = set((ROOT / ".env.example").read_text(encoding="utf-8").splitlines())

        self.assertIn("AIRFLOW_BASE_URL=http://localhost:8080/airflow", env_lines)
        self.assertIn(
            "AIRFLOW_EXECUTION_API_SERVER_URL=http://airflow-api-server:8080/airflow/execution/",
            env_lines,
        )

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
                '{"EMAIL_SEND_FALLBACK_OUTBOX": 0}',
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
            {"EMAIL_SEND_FALLBACK_OUTBOX": 0},
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

    def test_deployment_commit_must_match_exact_local_head(self):
        commit = "a" * 40

        self.assertTrue(production_health.deployment_commit_matches(commit, commit))
        self.assertFalse(production_health.deployment_commit_matches(commit, "b" * 40))
        self.assertFalse(production_health.deployment_commit_matches("main", "main"))

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


if __name__ == "__main__":
    unittest.main()
