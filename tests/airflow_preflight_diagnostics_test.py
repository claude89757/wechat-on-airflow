from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import diagnose_airflow_deploy_preflight  # noqa: E402


class AirflowPreflightDiagnosticsTest(TestCase):
    def test_remote_result_parser_ignores_non_structured_output(self) -> None:
        output = 'remote banner\n{"failed_stage": null, "ok": true}\n'

        self.assertEqual(
            diagnose_airflow_deploy_preflight.parse_remote_result(output),
            {"failed_stage": None, "ok": True},
        )

    def test_remote_diagnosis_reports_bounded_non_secret_stages(self) -> None:
        script = diagnose_airflow_deploy_preflight.remote_script()

        for stage in (
            "repository_path",
            "repository_git_status",
            "repository_worktree_dirty",
            "secret_directory_contract",
            "runtime_secret_missing",
            "runtime_secret_contract",
            "compose_unavailable",
            "compose_config",
            "api_service_not_running",
            "active_task_count",
        ):
            self.assertIn(f'failed_stage = "{stage}"', script)

        self.assertIn('"tracked_dirty_count": tracked_dirty_count', script)
        self.assertIn('"runtime_secret_missing_count": secret_missing_count', script)
        self.assertIn(
            '"runtime_secret_invalid_contract_count": secret_invalid_count',
            script,
        )
        self.assertNotIn("cat $secret_path", script)
        self.assertNotIn('cat "$secret_path"', script)
        self.assertNotIn('"secret_path"', script)
        self.assertNotIn('"secret_dir"', script)

    def test_protected_workflow_repairs_before_preflight_diagnosis_and_apply(self) -> None:
        workflow = (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")
        diagnostic = "scripts/diagnose_airflow_deploy_preflight.py"
        repair = "scripts/repair_airflow_worktree.py"

        self.assertEqual(workflow.count(diagnostic), 2)
        preflight_start = workflow.index("deploy_preflight)")
        self.assertLess(
            workflow.index(repair, preflight_start),
            workflow.index(diagnostic, preflight_start),
        )
        self.assertLess(
            workflow.index(diagnostic, preflight_start),
            workflow.index("scripts/deploy_airflow.py", preflight_start),
        )
        apply_start = workflow.index("deploy_apply)")
        self.assertLess(
            workflow.index(diagnostic, apply_start),
            workflow.index("scripts/deploy_airflow_transaction.py", apply_start),
        )
