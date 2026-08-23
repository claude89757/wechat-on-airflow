from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_gate_fails_fast_when_ci_record_is_missing():
    workflow = (ROOT / ".github/workflows/production-release.yml").read_text(encoding="utf-8")

    assert "--missing-check-wait-seconds 0" in workflow


def test_airflow_apply_uses_transactional_health_and_restore_wrapper():
    workflow = (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")

    assert workflow.count("scripts/deploy_airflow_transaction.py") == 2
    apply_block = workflow.split("deploy_apply)", 1)[1].split("db_cleanup_check)", 1)[0]
    assert "scripts/deploy_airflow.py --apply" not in apply_block


def test_runtime_drift_gate_is_explicit_in_ci():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate active components and runtime drift" in workflow
    assert "scripts/check_active_components.py" in workflow
