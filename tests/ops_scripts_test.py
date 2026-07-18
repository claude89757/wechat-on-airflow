from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import _ops  # noqa: E402
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


class ProductionHealthParsingTest(unittest.TestCase):
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
