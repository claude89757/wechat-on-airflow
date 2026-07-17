from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _ops  # noqa: E402
import production_health  # noqa: E402


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


class ProductionHealthParsingTest(unittest.TestCase):
    def test_parse_sections_separates_remote_command_output(self):
        output = "\n".join(
            [
                "__COMMIT__",
                "abc123",
                "__AIRFLOW_VERSION__",
                "3.3.0",
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


if __name__ == "__main__":
    unittest.main()
