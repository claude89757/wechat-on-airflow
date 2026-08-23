#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

SEMVER_TAG = re.compile(r"^(?:v)?\d+\.\d+\.\d+$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
VALID_SCOPES = {"auto", "all", "webapp", "airflow", "sender", "control"}

WEBAPP_RUNTIME_EXACT = {
    "webapp/index.html",
    "webapp/package.json",
    "webapp/package-lock.json",
    "webapp/tsconfig.json",
    "webapp/tsconfig.worker.json",
    "webapp/vite.config.ts",
    "webapp/wrangler.jsonc",
    "webapp/.npmrc",
    "webapp/scripts/prepare-sites-build.mjs",
}
WEBAPP_RUNTIME_PREFIXES = (
    "webapp/src/",
    "webapp/public/",
    "webapp/migrations/",
    "webapp/cloudflare/",
    "webapp/worker/",
    "webapp/.openai/",
)
WEBAPP_CI_EXACT = {
    "webapp/.gitignore",
    "webapp/playwright.config.ts",
    "webapp/mobile-runtime.lock.json",
    "webapp/scripts/check-mobile-runtime.mjs",
    "webapp/scripts/update-mobile-runtime-lock.mjs",
}
AIRFLOW_RUNTIME_EXACT = {
    "docker-compose.yml",
    "scripts/read_runtime_secret.py",
    "scripts/render_airflow_database_url.py",
}
AIRFLOW_RUNTIME_PREFIXES = (
    "dags/",
    "config/",
    "docker/airflow/",
    "src/wechat_airflow/",
)
SENDER_RUNTIME_EXACT = {
    "docker-compose.sender.yml",
    "deploy/systemd/wechat-sender.service",
    "deploy/systemd/appium-6002.override.conf",
    "scripts/install_wechat_sender.sh",
}
SENDER_RUNTIME_PREFIXES = (
    "sender_agent/",
    "wechat_sender/",
    "docker/sender/",
)
CONTROL_EXACT = {
    "Makefile",
    ".pre-commit-config.yaml",
}
METADATA_PREFIXES = (
    "docs/",
    ".agents/",
    "tests/",
    "webapp/qa/",
    "webapp/tests/",
)
METADATA_EXACT = {
    "CHANGELOG.md",
    "README.md",
    "README.en.md",
    "ARCHITECTURE.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "LICENSE",
    "webapp/design-qa.md",
    "webapp/AGENTS.md",
    "webapp/mobile-runtime.lock.json",
}


class PlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Plan:
    base_commit: str
    target_commit: str
    requested_scope: str
    resolved_scope: str
    changed_files: list[str]
    runtime_components: list[str]
    ci_components: list[str]
    control_plane_changed: bool
    metadata_only_files: list[str]
    unknown_files: list[str]
    deploy_webapp: bool
    deploy_airflow: bool
    deploy_sender: bool
    sender_approval_required: bool


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise PlanError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def resolve_commit(value: str) -> str:
    resolved = run_git("rev-parse", f"{value}^{{commit}}")
    if not COMMIT.fullmatch(resolved):
        raise PlanError(f"unable to resolve commit: {value}")
    return resolved


def previous_release_commit(target: str) -> str:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for tag in run_git("tag", "--merged", target).splitlines():
        if not SEMVER_TAG.fullmatch(tag):
            continue
        version = tag.removeprefix("v")
        parts = tuple(int(part) for part in version.split("."))
        commit = resolve_commit(tag)
        if commit != target:
            candidates.append((parts, commit))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    roots = run_git("rev-list", "--max-parents=0", target).splitlines()
    if not roots:
        raise PlanError("repository has no root commit")
    return resolve_commit(roots[-1])


def diff_files(base: str, target: str) -> list[str]:
    if base == target:
        return []
    output = run_git("diff", "--name-only", "--diff-filter=ACMRDTUXB", base, target, "--")
    return sorted(line for line in output.splitlines() if line)


def changed_payload_lines(base: str, target: str, path: str) -> list[str]:
    output = run_git("diff", "--unified=0", base, target, "--", path)
    lines: list[str] = []
    for line in output.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            lines.append(line)
    return lines


def version_metadata_only(base: str, target: str, path: str) -> bool:
    lines = changed_payload_lines(base, target, path)
    if not lines:
        return False
    if path == "pyproject.toml":
        pattern = re.compile(r'^[+-]version\s*=\s*"[^"]+"\s*$')
        return all(pattern.fullmatch(line) for line in lines)
    if path == "src/wechat_airflow/__init__.py":
        pattern = re.compile(r'^[+-]__version__\s*=\s*"[^"]+"\s*$')
        return all(pattern.fullmatch(line) for line in lines)
    return False


def starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def classify_file(
    base: str,
    target: str,
    path: str,
) -> tuple[set[str], set[str], bool, bool, bool]:
    """Return runtime components, CI components, control, metadata, unknown."""
    runtime: set[str] = set()
    ci: set[str] = set()
    control = False
    metadata = False
    unknown = False

    if path in {"pyproject.toml", "src/wechat_airflow/__init__.py"} and version_metadata_only(
        base, target, path
    ):
        return runtime, ci, control, True, unknown

    if path in WEBAPP_RUNTIME_EXACT or starts_with_any(path, WEBAPP_RUNTIME_PREFIXES):
        if path.endswith((".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx")):
            ci.add("webapp")
            metadata = True
        else:
            runtime.add("webapp")
            ci.add("webapp")
        return runtime, ci, control, metadata, unknown

    if (
        path in WEBAPP_CI_EXACT
        or starts_with_any(path, ("webapp/tests/", "webapp/qa/"))
        or path in {"webapp/design-qa.md", "webapp/AGENTS.md"}
    ):
        ci.add("webapp")
        return runtime, ci, control, True, unknown

    if path in AIRFLOW_RUNTIME_EXACT or starts_with_any(path, AIRFLOW_RUNTIME_PREFIXES):
        runtime.add("airflow")
        ci.add("airflow")
        return runtime, ci, control, metadata, unknown

    if path == "pyproject.toml":
        runtime.add("airflow")
        ci.update({"airflow", "sender", "webapp"})
        control = True
        return runtime, ci, control, metadata, unknown

    if path in SENDER_RUNTIME_EXACT or starts_with_any(path, SENDER_RUNTIME_PREFIXES):
        runtime.add("sender")
        ci.add("sender")
        return runtime, ci, control, metadata, unknown

    if path.startswith(".github/") or path in CONTROL_EXACT:
        control = True
        ci.update({"webapp", "airflow", "sender"})
        return runtime, ci, control, metadata, unknown

    if path.startswith("scripts/"):
        control = True
        ci.update({"webapp", "airflow", "sender"})
        return runtime, ci, control, metadata, unknown

    if starts_with_any(path, METADATA_PREFIXES) or path in METADATA_EXACT or path.endswith(".md"):
        return runtime, ci, control, True, unknown

    if path.startswith((".git", ".editorconfig")):
        return runtime, ci, control, True, unknown

    unknown = True
    ci.update({"webapp", "airflow", "sender"})
    runtime.update({"webapp", "airflow", "sender"})
    return runtime, ci, control, metadata, unknown


def resolve_scope(detected: set[str], requested: str) -> set[str]:
    if requested not in VALID_SCOPES:
        raise PlanError(f"unsupported scope: {requested}")
    if requested == "auto":
        return set(detected)
    if requested == "all":
        return {"webapp", "airflow", "sender"}
    if requested == "control":
        selected: set[str] = set()
    else:
        selected = {requested}
    missing = detected - selected
    if missing:
        raise PlanError(
            f"requested scope {requested!r} omits detected runtime components: "
            + ", ".join(sorted(missing))
        )
    return selected


def make_plan(base: str, target: str, scope: str, include_sender: bool) -> Plan:
    changed = diff_files(base, target)
    runtime: set[str] = set()
    ci: set[str] = set()
    control = False
    metadata_files: list[str] = []
    unknown_files: list[str] = []

    for path in changed:
        file_runtime, file_ci, file_control, metadata, unknown = classify_file(base, target, path)
        runtime.update(file_runtime)
        ci.update(file_ci)
        control = control or file_control
        if metadata:
            metadata_files.append(path)
        if unknown:
            unknown_files.append(path)

    selected = resolve_scope(runtime, scope)
    if "sender" in selected and not include_sender:
        raise PlanError("sender deployment is in scope; rerun with sender=true")

    if not selected:
        resolved = "control"
    elif selected == {"webapp", "airflow", "sender"}:
        resolved = "all"
    else:
        resolved = ",".join(
            component for component in ("webapp", "airflow", "sender") if component in selected
        )

    return Plan(
        base_commit=base,
        target_commit=target,
        requested_scope=scope,
        resolved_scope=resolved,
        changed_files=changed,
        runtime_components=sorted(runtime),
        ci_components=sorted(ci),
        control_plane_changed=control,
        metadata_only_files=metadata_files,
        unknown_files=unknown_files,
        deploy_webapp="webapp" in selected,
        deploy_airflow="airflow" in selected,
        deploy_sender="sender" in selected,
        sender_approval_required="sender" in runtime,
    )


def write_github_output(path: Path, plan: Plan) -> None:
    values = {
        "base_commit": plan.base_commit,
        "target_commit": plan.target_commit,
        "resolved_scope": plan.resolved_scope,
        "deploy_webapp": str(plan.deploy_webapp).lower(),
        "deploy_airflow": str(plan.deploy_airflow).lower(),
        "deploy_sender": str(plan.deploy_sender).lower(),
        "ci_webapp": str("webapp" in plan.ci_components).lower(),
        "ci_airflow": str("airflow" in plan.ci_components).lower(),
        "ci_sender": str("sender" in plan.ci_components).lower(),
        "control_plane_changed": str(plan.control_plane_changed).lower(),
        "changed_count": str(len(plan.changed_files)),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan component-scoped CI and production releases."
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--base-commit")
    parser.add_argument("--scope", choices=sorted(VALID_SCOPES), default="auto")
    parser.add_argument("--include-sender", action="store_true")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()

    target = resolve_commit(args.target_commit)
    base = resolve_commit(args.base_commit) if args.base_commit else previous_release_commit(target)
    plan = make_plan(base, target, args.scope, args.include_sender)

    if args.github_output:
        write_github_output(args.github_output, plan)
    payload = asdict(plan)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"scope={plan.resolved_scope} base={base} target={target}")
        print("changed=" + ",".join(plan.changed_files))


if __name__ == "__main__":
    try:
        main()
    except PlanError as exc:
        print(f"release-plan: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
