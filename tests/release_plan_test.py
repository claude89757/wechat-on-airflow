from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release_plan.py"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if success and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result


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


def test_control_plane_change_runs_all_ci_but_deploys_no_runtime(tmp_path: Path):
    repo, base = init_repo(tmp_path)
    write(repo, ".github/workflows/ci.yml", "name: CI\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "pipeline")
    target = git(repo, "rev-parse", "HEAD")

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
    write(repo, "sender_agent/app.py", "changed = True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "sender")

    result = run_plan(
        repo,
        "--target-commit",
        git(repo, "rev-parse", "HEAD"),
        success=False,
    )

    assert result.returncode == 2
    assert "rerun with sender=true" in result.stderr


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
