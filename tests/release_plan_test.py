from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release_plan.py"


def test_ci_keeps_full_regression_and_scoped_database() -> None:
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["schedule"]
    job = workflow["jobs"]["verify"]
    assert "services" not in job
    assert "full-regression" in job["name"]
    assert "'pr-check'" in job["name"]
    steps = {step.get("name"): step for step in job["steps"]}
    for name in (
        "Start isolated test database only for Python checks",
        "Install development dependencies",
        "Lint",
        "Type check",
        "Unit and workflow contract tests",
    ):
        assert steps[name]["if"] == "steps.plan.outputs.ci_python == 'true'"
    assert "echo 'ci_python=true'" in steps["Detect changed component surfaces"]["run"]
    assert '"$EVENT_NAME" == "pull_request"' in steps["Detect changed component surfaces"]["run"]
    assert steps["Fast pull request checks"]["if"] == "github.event_name == 'pull_request'"
    for name in ("Build Airflow image", "Build WeChat sender image", "Airflow 3 DAG imports"):
        assert "ci_images" in steps[name]["if"]
    for name in (
        "Install Chromium for focused Web browser checks",
        "Verify subscription and date-pause browser flows",
    ):
        assert steps[name]["if"] == "steps.plan.outputs.ci_browser == 'true'"
    assert "echo 'ci_browser=true'" in steps["Detect changed component surfaces"]["run"]


@pytest.mark.parametrize(
    "paths,expected",
    [
        (["scripts/example.py"], "false"),
        (["src/wechat_airflow/host_core/health.py"], "false"),
        (["webapp/qa/public-acceptance.mjs"], "false"),
        ([".github/workflows/ci.yml", "webapp/src/App.tsx"], "true"),
        (["webapp/tests/subscription-ux.spec.ts"], "true"),
        (["webapp/package-lock.json"], "true"),
        (["unknown.conf"], "true"),
    ],
)
def test_browser_checks_follow_browser_surfaces(tmp_path: Path, paths: list[str], expected: str):
    repo, base = init_repo(tmp_path)
    for path in paths:
        write(repo, path, "changed\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "browser scope")
    output = tmp_path / "outputs"
    run_plan(
        repo,
        "--base-commit",
        base,
        "--target-commit",
        git(repo, "rev-parse", "HEAD"),
        "--include-sender",
        "--github-output",
        str(output),
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["ci_browser"] == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("scripts/example.py", "false"),
        ("src/wechat_airflow/host_core/worker.py", "false"),
        ("dags/example.py", "true"),
        ("docker/sender/requirements.lock", "true"),
        ("unknown.conf", "true"),
    ],
)
def test_image_checks_follow_build_surfaces(tmp_path: Path, path: str, expected: str) -> None:
    repo, base = init_repo(tmp_path)
    target = commit_change(repo, path, "changed\n", "change")
    output = tmp_path / "outputs"
    run_plan(
        repo,
        "--base-commit",
        base,
        "--target-commit",
        target,
        "--include-sender",
        "--github-output",
        str(output),
    )
    assert f"ci_images={expected}" in output.read_text().splitlines()


def test_default_release_allows_interruption():
    import yaml

    release = yaml.safe_load((ROOT / ".github/workflows/production-release.yml").read_text())
    assert "'deploy_recovery'" in release["jobs"]["airflow"]["with"]["operation"]
    host = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    build = next(
        step
        for step in host["jobs"]["operate"]["steps"]
        if step.get("name") == "Build exact edge artifact"
    )
    assert "inputs.operation" in build["if"]
    assert "recovery-upgrade" in build["if"]
    assert "activate-workers" not in build["if"]
    resolve = next(step for step in host["jobs"]["resolve"]["steps"] if step.get("id") == "resolve")
    assert (
        '"$operation" == health || "$operation" == acceptance || "$operation" == pause'
        in resolve["run"]
    )
    prepare = next(
        step
        for step in host["jobs"]["operate"]["steps"]
        if step.get("name") == "Prepare exact remote commit"
    )
    assert 'test "$previous" = "$target"' in prepare["run"]
    assert 'test "$live" = "$target"' in prepare["run"]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("README.md", "false"),
        ("webapp/src/app.ts", "false"),
        ("pi_host/remote_ops/server.mjs", "false"),
        ("src/wechat_airflow/host_core/api.py", "true"),
        ("tests/example_test.py", "true"),
        ("scripts/release_plan.py", "true"),
        ("unknown.conf", "true"),
    ],
)
def test_python_gate_is_conservative(tmp_path: Path, path: str, expected: str) -> None:
    repo, base = init_repo(tmp_path)
    target = commit_change(repo, path, "changed\n", "change")
    output = tmp_path / "outputs"
    run_plan(
        repo,
        "--base-commit",
        base,
        "--target-commit",
        target,
        "--include-sender",
        "--github-output",
        str(output),
    )
    assert f"ci_python={expected}" in output.read_text().splitlines()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Release Plan Test")
    write(repo, "pyproject.toml", '[project]\nname = "example"\nversion = "0.2.0"\n')
    write(repo, "src/wechat_airflow/__init__.py", '__version__ = "0.2.0"\n')
    write(repo, "webapp/src/app.ts", "old\n")
    write(repo, "CHANGELOG.md", "# Changelog\n\n## [0.2.0] - 2026-08-23\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    git(repo, "tag", "0.2.0")
    return repo, git(repo, "rev-parse", "HEAD")


def run_plan(repo: Path, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if success and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


def commit_change(repo: Path, path: str, content: str, message: str) -> str:
    write(repo, path, content)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def test_web_change_with_version_metadata_resolves_to_webapp_only(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    write(repo, "webapp/src/app.ts", "new\n")
    write(repo, "pyproject.toml", '[project]\nname = "example"\nversion = "0.2.1"\n')
    write(repo, "src/wechat_airflow/__init__.py", '__version__ = "0.2.1"\n')
    write(repo, "CHANGELOG.md", "# Changelog\n\n## [0.2.1] - 2026-08-23\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "web patch")

    result = run_plan(repo, "--target-commit", git(repo, "rev-parse", "HEAD"))
    payload = json.loads(result.stdout)

    assert payload["resolved_scope"] == "webapp"
    assert payload["deploy_webapp"] is True
    assert payload["deploy_airflow"] is False
    assert payload["deploy_sender"] is False


def test_cloudflare_worker_source_is_webapp_runtime_only(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    target = commit_change(
        repo,
        "webapp/cloudflare/domain.ts",
        "export const changed = true;\n",
        "worker runtime",
    )

    payload = json.loads(run_plan(repo, "--target-commit", target).stdout)

    assert payload["runtime_components"] == ["webapp"]
    assert payload["ci_components"] == ["webapp"]
    assert payload["resolved_scope"] == "webapp"


def test_web_test_tooling_runs_web_ci_without_runtime_deploy(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    target = commit_change(
        repo,
        "webapp/playwright.config.ts",
        "export default {};\n",
        "browser test config",
    )

    payload = json.loads(run_plan(repo, "--target-commit", target).stdout)

    assert payload["runtime_components"] == []
    assert payload["ci_components"] == ["webapp"]
    assert payload["resolved_scope"] == "control"


def test_control_plane_change_runs_all_ci_but_deploys_no_runtime(tmp_path: Path):
    repo, base = init_repo(tmp_path)
    target = commit_change(repo, ".github/workflows/ci.yml", "name: CI\n", "pipeline")

    result = run_plan(
        repo,
        "--base-commit",
        base,
        "--target-commit",
        target,
    )
    payload = json.loads(result.stdout)

    assert payload["resolved_scope"] == "control"
    assert payload["runtime_components"] == []
    assert payload["ci_components"] == ["airflow", "sender", "webapp"]


def test_sender_change_requires_explicit_sender_approval(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    target = commit_change(repo, "sender_agent/app.py", "changed = True\n", "sender")

    result = run_plan(
        repo,
        "--target-commit",
        target,
        success=False,
    )

    assert result.returncode == 2
    assert "rerun with sender=true" in result.stderr


def test_sender_install_script_is_sender_runtime_and_can_be_approved(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    target = commit_change(
        repo,
        "scripts/install_wechat_sender.sh",
        "#!/usr/bin/env bash\nset -eu\n",
        "sender install",
    )

    payload = json.loads(
        run_plan(
            repo,
            "--target-commit",
            target,
            "--include-sender",
        ).stdout
    )

    assert payload["runtime_components"] == ["sender"]
    assert payload["resolved_scope"] == "sender"
    assert payload["deploy_sender"] is True


def test_manual_scope_cannot_omit_detected_runtime_component(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    write(repo, "webapp/src/app.ts", "new\n")
    write(repo, "dags/example.py", "DAG = object()\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "mixed")

    result = run_plan(
        repo,
        "--target-commit",
        git(repo, "rev-parse", "HEAD"),
        "--scope",
        "webapp",
        success=False,
    )

    assert result.returncode == 2
    assert "omits detected runtime components: airflow" in result.stderr


def test_pi_scrape_host_files_require_scraper_deployment_not_sender(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    write(repo, "pi_host/dsh_ydmap/server.py", "print('ok')\n")
    write(repo, "deploy/systemd/dsh-ydmap-scraper.service", "[Service]\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "pi host")

    payload = json.loads(run_plan(repo, "--target-commit", git(repo, "rev-parse", "HEAD")).stdout)

    assert payload["runtime_components"] == ["pi_ydmap"]
    assert payload["resolved_scope"] == "pi_ydmap"
    assert payload["deploy_pi_ydmap"] is True
    assert payload["deploy_sender"] is False
    assert payload["unknown_files"] == []


def test_airflow_scope_cannot_skip_required_scraper_update(tmp_path: Path):
    repo, _ = init_repo(tmp_path)
    target = commit_change(repo, "pi_host/dsh_ydmap/server.py", "changed = True\n", "scraper")
    result = run_plan(repo, "--target-commit", target, "--scope", "airflow", success=False)
    assert result.returncode == 2
    assert "omits detected runtime components: pi_ydmap" in result.stderr


def test_mcp_only_patch_emits_deployment_and_scoped_ci_outputs(tmp_path: Path):
    repo, base = init_repo(tmp_path)
    target = commit_change(repo, "pi_host/remote_ops/server.mjs", "export {};\n", "MCP patch")
    outputs = tmp_path / "outputs"
    payload = json.loads(
        run_plan(
            repo, "--base-commit", base, "--target-commit", target, "--github-output", str(outputs)
        ).stdout
    )
    assert payload["runtime_components"] == ["remote_ops"]
    assert payload["resolved_scope"] == "remote_ops"
    assert payload["deploy_remote_ops"] is True
    values = dict(line.split("=", 1) for line in outputs.read_text().splitlines())
    assert values["ci_remote_ops"] == "true"
    assert values["ci_pi_mcp"] == "false"
    assert all(
        values[key] == "false" for key in ("ci_webapp", "ci_airflow", "ci_sender", "deploy_pi_mcp")
    )
