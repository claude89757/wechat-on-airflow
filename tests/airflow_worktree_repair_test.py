from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import repair_airflow_worktree  # noqa: E402


class AirflowWorktreeRepairTest(TestCase):
    def test_remote_result_parser_ignores_non_structured_output(self) -> None:
        output = 'remote banner\n{"backup_created": true, "ok": true}\n'

        self.assertEqual(
            repair_airflow_worktree.parse_remote_result(output),
            {"backup_created": True, "ok": True},
        )

    def test_remote_repair_is_bounded_backed_up_and_non_destructive(self) -> None:
        script = repair_airflow_worktree.remote_script()

        self.assertIn("git status --porcelain --untracked-files=no", script)
        self.assertIn('"$tracked_dirty_count" -eq 0', script)
        self.assertIn('"$allow_clean" = "true"', script)
        self.assertIn('"already_clean": True', script)
        self.assertIn('"$tracked_dirty_count" -ne "$expected_dirty_count"', script)
        self.assertIn("git rev-parse --git-dir", script)
        self.assertIn("git diff --binary --full-index --no-ext-diff HEAD", script)
        self.assertIn('chmod 600 "$patch_file"', script)
        self.assertIn("git reset --hard HEAD", script)
        self.assertIn('git apply --check --binary "$patch_file"', script)
        self.assertIn('"untracked_files_preserved": True', script)
        self.assertIn('"services_restarted": False', script)
        self.assertIn('"database_unchanged": True', script)
        self.assertNotIn("git clean", script)
        self.assertNotIn("docker compose down", script)
        self.assertNotIn("rm -rf", script)
        self.assertNotIn('"patch_file"', script)
        self.assertNotIn('"metadata_file"', script)

    def test_remote_metadata_uses_python_3_8_compatible_utc(self) -> None:
        script = repair_airflow_worktree.remote_script()

        self.assertIn("from datetime import datetime, timezone", script)
        self.assertIn("datetime.now(timezone.utc)", script)
        self.assertNotIn("from datetime import UTC", script)

    def test_verification_accepts_repaired_and_already_clean_results(self) -> None:
        common = {
            "ok": True,
            "tracked_dirty_count_after": 0,
            "services_restarted": False,
            "database_unchanged": True,
            "untracked_files_preserved": True,
        }
        repaired = {
            **common,
            "already_clean": False,
            "applied": True,
            "backup_created": True,
            "backup_restore_check": True,
            "tracked_dirty_count_before": 1,
        }
        already_clean = {
            **common,
            "already_clean": True,
            "applied": False,
            "backup_created": False,
            "tracked_dirty_count_before": 0,
        }

        self.assertTrue(repair_airflow_worktree.repair_succeeded(repaired, 1))
        self.assertTrue(repair_airflow_worktree.repair_succeeded(already_clean, 1))

    def test_protected_preflight_repairs_then_diagnoses_then_dry_runs(self) -> None:
        workflow = (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")
        operation = workflow.index("deploy_preflight)")
        repair = workflow.index("scripts/repair_airflow_worktree.py", operation)
        diagnose = workflow.index("scripts/diagnose_airflow_deploy_preflight.py", repair)
        dry_run = workflow.index("scripts/deploy_airflow.py", diagnose)

        self.assertLess(repair, diagnose)
        self.assertLess(diagnose, dry_run)
        self.assertIn("--expected-dirty-count 1", workflow)
        self.assertIn("--if-needed", workflow)
        self.assertNotIn("airflow_worktree_repair)", workflow)
