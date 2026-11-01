from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize(
    "component,directory", [("remote_ops", "remote_ops"), ("pi_mcp", "appium_mcp")]
)
def test_mcp_runtime_cannot_be_silently_omitted(component, directory):
    module = load("release_plan")
    runtime, ci, _, metadata, unknown = module.classify_file(
        "a" * 40, "b" * 40, f"pi_host/{directory}/server.mjs"
    )
    assert runtime == ci == {component}
    assert not metadata and not unknown
    with pytest.raises(module.PlanError, match="omits detected"):
        module.resolve_scope(runtime, "control")
    assert component in module.resolve_scope(runtime, "all")
    assert module.resolve_scope(runtime, component) == runtime


@pytest.mark.parametrize(
    "path,component",
    [
        ("pi_host/remote_ops/test/example.test.mjs", "remote_ops"),
        ("pi_host/appium_mcp/test/example.test.mjs", "pi_mcp"),
        ("pi_host/remote_ops/README.md", "remote_ops"),
    ],
)
def test_mcp_tests_and_docs_never_deploy(path, component):
    runtime, ci, _, metadata, _ = load("release_plan").classify_file("a" * 40, "b" * 40, path)
    assert runtime == set()
    assert ci == {component}
    assert metadata


@pytest.mark.parametrize(
    "path",
    [
        "scripts/deploy_remote_ops_mcp.py",
        ".github/workflows/production-remote-ops-mcp.yml",
        "scripts/mcp_lifecycle.py",
    ],
)
def test_known_mcp_tooling_does_not_build_unrelated_components(path):
    runtime, ci, control, _, _ = load("release_plan").classify_file("a" * 40, "b" * 40, path)
    assert not runtime and control
    assert ci and ci.isdisjoint({"webapp", "airflow", "sender"})


@pytest.mark.parametrize("failed", [None, "preflight", "apply", "health"])
def test_lifecycle_stops_on_first_failure(failed):
    calls = []

    def runner(args, *, env, check):
        assert check
        assert args[-1] == "scripts/deploy_remote_ops_mcp.py"
        calls.append(env["OPERATION"])
        if env["OPERATION"] == failed:
            raise subprocess.CalledProcessError(1, args)

    module = load("mcp_lifecycle")
    if failed:
        with pytest.raises(subprocess.CalledProcessError):
            module.lifecycle("remote_ops", runner)
    else:
        module.lifecycle("remote_ops", runner)
    phases = ["preflight", "apply", "health"]
    assert calls == (phases[: phases.index(failed) + 1] if failed else phases)


def test_unified_release_and_ci_preserve_gates_and_component_selection():
    pipeline = workflow("production-release.yml")
    for component in ("remote_ops", "pi_mcp"):
        job = pipeline["jobs"][component]
        assert job["uses"] == "./.github/workflows/production-mcp.yml"
        assert job["needs"] == "gate"
        assert component in pipeline["jobs"]["record"]["needs"]
        assert job["secrets"] == "inherit"
    for name in ("production-remote-ops-mcp.yml", "production-appium-mcp.yml"):
        job = workflow(name)["jobs"]["operate"]
        assert job["environment"] == "production"
        source = "\n".join(step.get("run", "") for step in job["steps"])
        assert "github_release_gate.py" in source
        assert "mcp_lifecycle.py" in source
    ci = workflow("ci.yml")
    step = next(
        s
        for s in ci["jobs"]["verify"]["steps"]
        if s.get("name") == "Verify administrator MCP without real hosts"
    )
    assert step["if"] == "steps.plan.outputs.ci_remote_ops == 'true'"
    lifecycle = workflow("production-mcp.yml")
    assert lifecycle["jobs"]["vps"]["needs"] == ["validate", "pi"]
    assert all(lifecycle["jobs"][name]["secrets"] == "inherit" for name in ("pi", "vps", "phone"))


def test_retired_formatter_and_unnecessary_permission_are_removed():
    router = workflow("ops-chatops.yml")
    assert "pull-requests" not in router["permissions"]
    assert "format_host_core" not in router["jobs"]
    assert "/format-host-core" not in (ROOT / ".github/workflows/ops-chatops.yml").read_text()
    assert "pi_tunnel_diagnose" in router["jobs"]
