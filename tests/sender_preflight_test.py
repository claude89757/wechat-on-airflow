from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from scripts.sender_wheelhouse import FAILURE_KINDS

ROOT = Path(__file__).resolve().parents[1]


def remote_shell():
    tree = ast.parse((ROOT / "scripts/deploy_wechat_sender.py").read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "remote_script"
    )
    return ast.literal_eval(function.body[0].value)


def preflight_python():
    shell = remote_shell()
    return shell.split("<<'DEPENDENCY_PREFLIGHT_PY'\n", 1)[1].split("\nDEPENDENCY_PREFLIGHT_PY", 1)[
        0
    ]


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, None),
        ("python", "unsupported_service_python"),
        ("wheel", "candidate_locked_install_failed"),
        ("timeout", "candidate_locked_install_failed"),
        ("process", "candidate_locked_install_failed"),
        ("smoke", "candidate_image_smoke_failed"),
        ("prefix", "active_service_or_rollback_unavailable"),
        ("disk", "insufficient_staging_disk"),
        ("identity", "runtime_identity_mismatch"),
        ("candidate_python", "candidate_interpreter_mismatch"),
        ("artifact", "candidate_staged_artifact_invalid"),
        ("tag_inventory", "candidate_staged_artifact_invalid"),
    ],
)
@pytest.mark.parametrize("minor", [11, 12])
@pytest.mark.parametrize("arm32", [False, True])
def test_candidate_preflight_never_mutates_active_runtime(
    tmp_path, failure, expected, minor, arm32
):
    if failure in {"artifact", "tag_inventory"} and not arm32:
        # Other interpreters never inspect or require this ARM-only artifact.
        expected = None
    if (
        arm32
        and minor == 12
        and failure in {None, "wheel", "timeout", "process", "smoke", "artifact"}
    ):
        expected = "candidate_staged_artifact_invalid"
    succeeds = expected is None
    active = tmp_path / "active"
    (active / "bin").mkdir(parents=True)
    (active / "bin/python").write_text("existing interpreter")
    original = (active / "bin/python").read_bytes()
    calls = []
    install_environments = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "install" in argv:
            install_environments.append(kwargs.get("env"))
        output = ""
        code = 0
        error = "PRIVATE PACKAGE INDEX MUST NOT APPEAR"
        if argv[:2] == ["systemctl", "is-enabled"]:
            output = "enabled"
        elif argv[:2] == ["systemctl", "is-active"]:
            output = "active"
        elif argv[:2] == ["systemctl", "show"]:
            output = (
                f"{{ path={active}/bin/python{'-unexpected' if failure == 'prefix' else ''} ; }}"
            )
        elif argv[0] == "curl":
            output = (
                '{"ok":true,"deploymentCommit":"'
                + ("c" if failure == "identity" else "a") * 40
                + '"}'
            )
        elif argv[:3] == [str(active / "bin/python"), "-m", "venv"]:
            environment = Path(argv[-1])
            (environment / "bin").mkdir(parents=True)
            (environment / "bin/python").touch()
        elif argv[0] == str(active / "bin/python"):
            output = json.dumps(
                {
                    "python": f"3.{10 if failure == 'python' else minor}.9",
                    "pillow": "12.3.0",
                    "inside_prefix": False,
                    "bits": 32 if arm32 else 64,
                    "platform": "linux-aarch64",
                }
            )
        elif argv[0].endswith("venv/bin/python") and argv[1] == "-c":
            output = json.dumps(
                {
                    "python": f"3.{13 if failure == 'candidate_python' else minor}.9",
                    "bits": 32 if arm32 else 64,
                    "platform": "linux-aarch64",
                    "pip_version": "22.3.1",
                    "pip_tag_inventory_available": failure != "tag_inventory",
                    "pip_arm32_tags": arm32,
                    "pip_arm64_tags": not arm32,
                    "pip_native_cpython_abi": True,
                }
            )
        elif argv[1].endswith("sender_wheelhouse.py"):
            output = "true"
            if failure == "artifact":
                code = 1
                error = "sha256_mismatch"
            if arm32 and minor == 12:
                code = 1
                error = "tag_mismatch"
        elif "show" in argv:
            if argv[-1].endswith("requirements.lock"):
                output = (ROOT / "docker/sender/requirements.lock").read_text()
            elif argv[-1].endswith("sender-arm32-wheelhouse.json"):
                output = (ROOT / "config/sender-arm32-wheelhouse.json").read_text()
            else:
                output = "# candidate checker"
        elif "install" in argv and failure == "wheel":
            code = 1
        elif "install" in argv and failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 300, output="PRIVATE TIMEOUT")
        elif "install" in argv and failure == "process":
            raise OSError("PRIVATE PROCESS FAILURE")
        elif (
            argv[0].endswith("venv/bin/python")
            and argv[1].endswith("verify_dependencies.py")
            and failure == "smoke"
        ):
            code = 1
        return subprocess.CompletedProcess(argv, code, output, error)

    output = io.StringIO()
    with (
        patch(
            "sys.argv",
            [
                "probe",
                "a" * 40,
                "b" * 40,
                str(tmp_path / "checkout"),
                str(active),
                "/tmp/upload.whl",
            ],
        ),
        patch("subprocess.run", side_effect=run),
        patch.dict(
            os.environ,
            {
                "PIP_FIND_LINKS": "https://PRIVATE.invalid",
                "PIP_CONFIG_FILE": "/PRIVATE/pip.conf",
                "PIP_INDEX_URL": "https://secret@PRIVATE.invalid",
                "KEEP_TEST_VALUE": "retained",
            },
        ),
        patch("shutil.which", side_effect=AssertionError("must not select interpreter from PATH")),
        patch(
            "shutil.disk_usage",
            return_value=SimpleNamespace(free=0 if failure == "disk" else 2**32),
        ),
        contextlib.redirect_stdout(output),
        pytest.raises(SystemExit) as stopped,
    ):
        exec(compile(preflight_python(), "sender-preflight", "exec"), {})
    report = json.loads(output.getvalue())
    assert stopped.value.code == (0 if succeeds else 1)
    assert report["ok"] is succeeds
    assert report.get("failure_category") == expected
    assert report["active_environment_changed"] is False
    assert report["external_test_sends"] == 0
    assert "PRIVATE" not in output.getvalue()
    assert (active / "bin/python").read_bytes() == original
    assert not list(tmp_path.glob(".sender-preflight-*"))
    assert not any("restart" in argv or "checkout" in argv for argv in calls)
    if failure in {"wheel", "timeout", "process"} and expected == "candidate_locked_install_failed":
        assert (
            report["candidate_install_failure_kind"]
            == {
                "wheel": "unclassified",
                "timeout": "timeout",
                "process": "process_start_failed",
            }[failure]
        )
        assert report.get("candidate_install_exit_code") == (1 if failure == "wheel" else None)
        assert report["candidate_failure_phase"] == "locked_install"
    if expected == "candidate_staged_artifact_invalid":
        assert report["candidate_failure_phase"] == "staged_artifact_validation"
        assert report["candidate_artifact_failure_kind"] == (
            "tag_inventory_failed"
            if failure == "tag_inventory"
            else "tag_mismatch"
            if minor == 12
            else "sha256_mismatch"
        )
        assert report["candidate_staged_artifact_verified"] is False
        assert not any("install" in argv for argv in calls)
    if succeeds:
        assert report["runtime_commit"] == "a" * 40
        assert report["candidate_pillow"] == "13.0.0"
        assert report["candidate_python"] == f"3.{minor}.9"
        assert report["candidate_python_bits"] == (32 if arm32 else 64)
        assert report["active_python_platform"] == "linux-aarch64"
        assert report["active_pillow"] == "12.3.0"
        assert report["active_pillow_inside_prefix"] is False
        assert report["candidate_locked_dependencies_verified"] is True
        assert report["temporary_environment_removed"] is True
        assert report["candidate_pip_version"] == "22.3.1"
        assert report["candidate_pip_tag_inventory_available"] is (failure != "tag_inventory")
        assert report["candidate_pip_arm32_tags"] is arm32
        assert report["candidate_pip_arm64_tags"] is (not arm32)
        assert report["candidate_arm32_wheelhouse_source"] is arm32
        assert report["candidate_staged_artifact_verified"] is arm32
        assert report["candidate_pip_native_cpython_abi"] is True
        assert "candidate_install_failure_kind" not in report
        assert any(
            ("--only-binary=:all:" if arm32 else "--only-binary=Pillow") in argv for argv in calls
        )
        assert any(argv[-1] == "b" * 40 + ":docker/sender/requirements.lock" for argv in calls)
        assert any(argv[-1] == "b" * 40 + ":sender_agent/verify_dependencies.py" for argv in calls)
        installs = [argv for argv in calls if "install" in argv]
        assert len(installs) == 1
        assert ("--find-links" in installs[0]) is arm32
        if arm32:
            assert any(argv[-1] == "b" * 40 + ":scripts/sender_wheelhouse.py" for argv in calls)
            assert Path(installs[0][installs[0].index("--find-links") + 1]).name == "wheelhouse"
            assert "--no-index" in installs[0] and "--isolated" in installs[0]
            assert report["candidate_staged_wheel_count"] == 27
            assert install_environments[0]["PIP_CONFIG_FILE"] == os.devnull
            assert install_environments[0]["KEEP_TEST_VALUE"] == "retained"
            assert {key for key in install_environments[0] if key.startswith("PIP_")} == {
                "PIP_CONFIG_FILE"
            }
        else:
            assert "--no-index" not in installs[0] and "--isolated" not in installs[0]
            assert install_environments == [None]
        assert "candidate_failure_phase" not in report


def test_both_official_modes_gate_before_activation_and_source_checkout():
    shell = remote_shell()
    dry_run = shell.split('if [ "$mode" = "dry-run" ]; then', 1)[1].split(
        'test "$mode" = "apply"', 1
    )[0]
    apply = shell.split('test "$mode" = "apply"', 1)[1]
    assert dry_run.index("fetch_target") < dry_run.index("dependency_preflight")
    assert apply.index("fetch_target") < apply.index("dependency_preflight")
    assert apply.index("dependency_preflight") < apply.index("unit_backup=")
    assert apply.index("dependency_preflight") < apply.index("trap rollback EXIT")
    assert apply.index("dependency_preflight") < apply.index(
        'checkout --quiet --detach "$target_commit"'
    )
    assert "--only-binary=Pillow" in preflight_python()
    assert "--platform" not in preflight_python()
    assert '"--upgrade"' not in preflight_python()
    assert "stderr=subprocess.PIPE" in preflight_python()
    assert "universal_newlines=True" in preflight_python()
    result = subprocess.run(
        ["bash", "-n"], input=shell, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_inventory_is_compatible_with_python36_syntax_and_api():
    probe = preflight_python()
    ast.parse(probe, feature_version=(3, 6))
    assert "capture_output=" not in probe
    assert "text=True" not in probe
    assert "is_relative_to" not in probe
    assert "os.path.commonpath" in probe
    assert 'getattr(platform, "freedesktop_os_release", lambda: {})' in probe


@pytest.mark.parametrize("succeeded", [True, False])
def test_dry_run_preserves_preflight_inventory_in_final_output(succeeded):
    report = {"stage": "sender_dependency_preflight", "ok": succeeded, "active_pillow": "12.3.0"}
    if not succeeded:
        report["failure_category"] = "unsupported_service_python"
    shell = remote_shell()
    block = (
        'if [ "$mode" = "dry-run" ]; then'
        + shell.split('if [ "$mode" = "dry-run" ]; then', 1)[1].split('test "$mode" = "apply"', 1)[
            0
        ]
    )
    script = (
        "set -eu\nmode=dry-run\ncredentials_ready=true\ncurrent_commit=old\ntarget_commit=new\n"
        "preserve_reviewed_drift() { :; }\nfetch_target() { :; }\n"
        f'dependency_preflight() {{ printf "%s\\n" {shlex.quote(json.dumps(report))}; return {0 if succeeded else 1}; }}\n'
        f'python3() {{ {shlex.quote(sys.executable)} "$@"; }}\n' + block
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == (0 if succeeded else 1), result.stderr
    actual = json.loads(result.stdout)
    assert (actual["dependency_preflight"] if succeeded else actual) == report


@pytest.mark.parametrize("known_stage", [True, False])
def test_remote_failure_emits_only_allowlisted_inventory_not_stderr(known_stage):
    source = (ROOT / "scripts/deploy_wechat_sender.py").read_text()
    tree = ast.parse(source)
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"parse_remote_result", "safe_dependency_preflight"}
    ]
    emitted = []

    class OpsError(Exception):
        pass

    namespace = {
        "Any": Any,
        "json": json,
        "re": re,
        "OpsError": OpsError,
        "COMMIT_PATTERN": re.compile(r"^[0-9a-f]{40}$"),
        "FAILURE_KINDS": FAILURE_KINDS,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "helpers", "exec"), namespace)
    report = {
        "stage": "sender_dependency_preflight" if known_stage else "other",
        "ok": False,
        "active_python": "3.6.9",
        "active_pillow": "5.1.0",
        "failure_category": "unsupported_service_python",
        "secret": "PRIVATE VALUE",
        "distribution": {"ID": "ubuntu", "VERSION_ID": "18.04", "secret": "PRIVATE VALUE"},
    }
    namespace.update(
        {
            "result": subprocess.CompletedProcess([], 1, json.dumps(report), "PRIVATE STDERR"),
            "args": SimpleNamespace(format="json"),
            "emit": lambda value, format: emitted.append(value),
        }
    )
    failure = source.split("    if result.returncode:\n        try:\n            failure =", 1)[
        1
    ].split("    payload = parse_remote_result(result.stdout)", 1)[0]
    body = "if result.returncode:\n        try:\n            failure =" + failure
    with pytest.raises(OpsError, match="sender operation failed") as error:
        exec(compile(body, "failure-emission", "exec"), namespace)
    assert "PRIVATE" not in str(error.value)
    assert "PRIVATE" not in json.dumps(emitted)
    if known_stage:
        assert emitted[0]["failure_category"] == "unsupported_service_python"
        assert emitted[0]["active_python"] == "3.6.9"
        assert emitted[0]["distribution"] == {"ID": "ubuntu", "VERSION_ID": "18.04"}
    else:
        assert emitted == []


def diagnostic_helpers():
    names = {"PreflightFailure", "install_failure_diagnostics", "record_install_failure", "command"}
    nodes = [
        node
        for node in ast.parse(preflight_python()).body
        if isinstance(node, ast.ClassDef | ast.FunctionDef) and node.name in names
    ]
    namespace = {"re": re, "os": os, "subprocess": subprocess, "report": {}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "diagnostics", "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "detail,kind,pin",
    [
        (
            "ERROR: No matching distribution found for pillow==13.0.0",
            "no_matching_distribution",
            "Pillow==13.0.0",
        ),
        (
            "ERROR: Could not find a version that satisfies the requirement pydantic-core==2.46.4 (from versions: none)",
            "no_matching_distribution",
            "pydantic_core==2.46.4",
        ),
        (
            "SSLError CERTIFICATE_VERIFY_FAILED; No matching distribution found for Pillow==13.0.0",
            "network_tls",
            "Pillow==13.0.0",
        ),
        ("Temporary failure in name resolution; Max retries exceeded", "network_connection", None),
        ("401 Client Error: authentication required", "index_authentication", None),
        ("ResolutionImpossible: conflicting dependencies", "dependency_resolution", None),
        ("Failed building wheel for something", "build_failed", None),
        ("unrecognized error", "unclassified", None),
        ("No matching distribution found for Pillow==99.0.0", "no_matching_distribution", None),
        ("No matching distribution found for PRIVATE==13.0.0", "no_matching_distribution", None),
    ],
)
def test_install_failure_reports_only_fixed_kind_and_exact_locked_requirement(detail, kind, pin):
    classify = diagnostic_helpers()["install_failure_diagnostics"]
    report = classify(
        "PRIVATE_STDOUT https://secret-user:secret-token@private-index.invalid/simple",
        detail + "\nPRIVATE_STDERR /private/home/private-token",
        "Pillow==13.0.0\npydantic_core==2.46.4\n",
        1,
    )
    assert report["candidate_install_failure_kind"] == kind
    assert report["candidate_install_exit_code"] == 1
    assert report.get("candidate_failed_requirement") == pin
    rendered = json.dumps(report)
    for private in (
        "PRIVATE",
        "https://",
        "secret-user",
        "secret-token",
        "private-index",
        "/private",
    ):
        assert private not in rendered


def test_optional_diagnostics_error_preserves_original_install_failure():
    namespace = diagnostic_helpers()
    broken_lock = SimpleNamespace(read_text=lambda: (_ for _ in ()).throw(OSError("PRIVATE")))
    with patch(
        "subprocess.run", return_value=subprocess.CompletedProcess([], 1, "PRIVATE", "PRIVATE")
    ):
        with pytest.raises(
            namespace["PreflightFailure"], match="^candidate_locked_install_failed$"
        ):
            namespace["command"](
                ["synthetic-pip"], "candidate_locked_install_failed", install_lock=broken_lock
            )
    assert namespace["report"] == {
        "candidate_install_failure_kind": "unclassified",
        "candidate_install_exit_code": 1,
    }


@pytest.mark.parametrize("output_type", ["bytes", "text", "none"])
def test_timeout_preserves_bounded_partial_evidence_without_changing_failure(tmp_path, output_type):
    namespace = diagnostic_helpers()
    lock = tmp_path / "requirements.lock"
    lock.write_text("Pillow==13.0.0\npydantic_core==2.46.4\n")
    output = "Collecting pydantic-core==2.46.4 (from -r /PRIVATE/lock)\n  Building wheel for pydantic-core (pyproject.toml): started\n"
    error = "WARNING: Retrying (Retry(total=4)) after connection broken by ConnectTimeoutError at https://secret@PRIVATE.invalid\n"
    if output_type == "bytes":
        output, error = output.encode() + b"\xff", error.encode()
    elif output_type == "none":
        output, error = None, None
    argv = ["synthetic-pip", "install", "--only-binary=Pillow"]
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(argv, 300, output=output, stderr=error),
    ) as invoked:
        with pytest.raises(
            namespace["PreflightFailure"], match="^candidate_locked_install_failed$"
        ):
            namespace["command"](argv, "candidate_locked_install_failed", 300, install_lock=lock)
    invoked.assert_called_once_with(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=300,
        check=False,
    )
    report = namespace["report"]
    assert report["candidate_install_failure_kind"] == "timeout"
    assert report["candidate_install_observed_progress"] == (
        "not_observed" if output_type == "none" else "wheel_build"
    )
    assert report["candidate_install_network_evidence"] == (
        "not_observed" if output_type == "none" else "network_connection"
    )
    assert report.get("candidate_install_last_observed_requirement") == (
        None if output_type == "none" else "pydantic_core==2.46.4"
    )
    assert "candidate_failed_requirement" not in report
    assert "candidate_install_exit_code" not in report
    for private in ("PRIVATE", "https://", "secret", "/lock"):
        assert private not in json.dumps(report)


@pytest.mark.parametrize(
    "line,progress",
    [
        ("Collecting Pillow==13.0.0", "collecting"),
        ("Processing /PRIVATE/wheel.whl", "collecting"),
        ("Downloading https://secret@PRIVATE.invalid/file", "retrieval"),
        ("Using cached /PRIVATE/file", "retrieval"),
        ("Installing build dependencies ...", "build_dependencies"),
        ("Getting requirements to build wheel ...", "build_requirements"),
        ("Preparing metadata (pyproject.toml) ...", "metadata"),
        ("Building wheel for PRIVATE (pyproject.toml): started", "wheel_build"),
        ("Installing collected packages: PRIVATE", "installing_packages"),
        (
            "INFO: pip is looking at multiple versions of PRIVATE to determine which version is compatible",
            "resolver_backtracking",
        ),
        (
            "INFO: This is taking longer than usual. You might need to provide the dependency resolver with stricter constraints",
            "resolver_backtracking",
        ),
    ],
)
def test_timeout_progress_is_fixed_stdout_evidence_not_cross_stream_order(line, progress):
    classify = diagnostic_helpers()["install_failure_diagnostics"]
    report = classify(
        "Collecting pydantic_core==2.46.4\n" + line + "\n",
        "Collecting Pillow==13.0.0\nDownloading PRIVATE\nSSLError CERTIFICATE_VERIFY_FAILED\n",
        "Pillow==13.0.0\npydantic_core==2.46.4\n",
        exception_kind="timeout",
    )
    assert report["candidate_install_observed_progress"] == progress
    assert report["candidate_install_network_evidence"] == "network_tls"
    assert report["candidate_install_failure_kind"] == "timeout"
    assert "candidate_failed_requirement" not in report
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize(
    "stderr,network",
    [
        ("401 Client Error: authentication required PRIVATE", "index_authentication"),
        ("WARNING: Retrying (Retry(total=3)) PRIVATE", "retry_observed"),
        ("ReadTimeoutError PRIVATE", "network_connection"),
        ("unrecognized PRIVATE output", "not_observed"),
    ],
)
def test_timeout_network_evidence_is_separate_from_timeout_kind(stderr, network):
    report = diagnostic_helpers()["install_failure_diagnostics"](
        "", stderr, "", exception_kind="timeout"
    )
    assert report["candidate_install_failure_kind"] == "timeout"
    assert report["candidate_install_network_evidence"] == network
    assert report["candidate_install_observed_progress"] == "not_observed"


def test_timeout_tail_is_bounded_and_last_observed_requirement_must_match_lock():
    classify = diagnostic_helpers()["install_failure_diagnostics"]
    report = classify(
        b"Collecting Pillow==13.0.0\n"
        + b"x" * 32768
        + b"\nCollecting pydantic-core==2.46.4\nCollecting PRIVATE==1.0\nCollecting Pillow==99.0.0\nCollecting Pillow @ https://secret@PRIVATE.invalid\n",
        b"SSLError CERTIFICATE_VERIFY_FAILED\n" + b"x" * 32768,
        "Pillow==13.0.0\npydantic_core==2.46.4\n",
        exception_kind="timeout",
    )
    assert report["candidate_install_network_evidence"] == "not_observed"
    assert report["candidate_install_last_observed_requirement"] == "pydantic_core==2.46.4"
    assert "candidate_failed_requirement" not in report
    assert "PRIVATE" not in json.dumps(report)


def test_partial_bytes_still_identify_explicit_failure_as_distinct_from_observed_requirement():
    report = diagnostic_helpers()["install_failure_diagnostics"](
        b"Collecting pydantic-core==2.46.4\n",
        b"ERROR: No matching distribution found for Pillow==13.0.0\n",
        "Pillow==13.0.0\npydantic_core==2.46.4\n",
        exception_kind="timeout",
    )
    assert report["candidate_install_failure_kind"] == "timeout"
    assert report["candidate_install_last_observed_requirement"] == "pydantic_core==2.46.4"
    assert report["candidate_failed_requirement"] == "Pillow==13.0.0"


def safe_inventory(value):
    nodes = [
        node
        for node in ast.parse((ROOT / "scripts/deploy_wechat_sender.py").read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "safe_dependency_preflight"
    ]
    namespace = {
        "Any": Any,
        "re": re,
        "REPO_ROOT": ROOT,
        "COMMIT_PATTERN": re.compile(r"^[0-9a-f]{40}$"),
        "FAILURE_KINDS": FAILURE_KINDS,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "safe-inventory", "exec"), namespace)
    return namespace["safe_dependency_preflight"]({"stage": "sender_dependency_preflight", **value})


def test_timeout_inventory_independently_validates_enum_types_and_exact_lock_pin():
    fields = {
        "candidate_install_network_evidence": "retry_observed",
        "candidate_install_observed_progress": "build_dependencies",
        "candidate_install_last_observed_requirement": "pydantic_core==2.46.4",
    }
    clean = safe_inventory(fields)
    assert {key: clean[key] for key in fields} == fields
    for key in fields:
        for bad in (
            True,
            None,
            [],
            {},
            1,
            "PRIVATE",
            "Pillow==99.0.0",
            "pydantic_core==2.46.4\nPRIVATE",
        ):
            assert key not in safe_inventory({key: bad})


def test_failure_inventory_independently_validates_new_fields_against_repository_lock():
    fields = {
        "candidate_pip_version": "22.3.1",
        "candidate_pip_tag_inventory_available": True,
        "candidate_pip_arm32_tags": True,
        "candidate_pip_arm64_tags": False,
        "candidate_pip_native_cpython_abi": True,
        "candidate_install_failure_kind": "no_matching_distribution",
        "candidate_install_exit_code": 1,
        "candidate_failed_requirement": "Pillow==13.0.0",
    }
    cleaned = safe_inventory(fields)
    assert {key: cleaned[key] for key in fields} == fields
    for bad in (
        "Pillow==99.0.0",
        "PRIVATE==13.0.0",
        "https://private:secret@index.invalid",
        "Pillow==13.0.0\nPRIVATE",
    ):
        assert "candidate_failed_requirement" not in safe_inventory(
            {"candidate_failed_requirement": bad}
        )
    for bad in ("PRIVATE", "9" * 41 + ".1", "22.3.1 https://private.invalid"):
        assert "candidate_pip_version" not in safe_inventory({"candidate_pip_version": bad})
    for bad in (True, 256, -256, "PRIVATE"):
        assert "candidate_install_exit_code" not in safe_inventory(
            {"candidate_install_exit_code": bad}
        )
    assert (
        safe_inventory({"candidate_install_failure_kind": "PRIVATE"})[
            "candidate_install_failure_kind"
        ]
        == "unclassified"
    )


@pytest.mark.parametrize("inventory_error", [False, True])
def test_candidate_tag_inventory_reports_booleans_without_private_output(inventory_error):
    from types import ModuleType

    probe = next(
        ast.literal_eval(node.value)
        for node in ast.walk(ast.parse(preflight_python()))
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "candidate_probe"
            for target in node.targets
        )
    )
    pip = ModuleType("pip")
    pip.__version__ = "22.3.1"
    tags_module = ModuleType("pip._internal.utils.compatibility_tags")

    def supported():
        print("PRIVATE INDEX https://secret@private.invalid")
        print("PRIVATE STDERR", file=sys.stderr)
        if inventory_error:
            raise SystemExit("PRIVATE CONFIG ERROR")
        return [
            SimpleNamespace(
                platform="linux_armv7l", abi=f"cp{sys.version_info.major}{sys.version_info.minor}"
            )
        ]

    tags_module.get_supported = supported
    output = io.StringIO()
    errors = io.StringIO()
    with (
        patch.dict(
            sys.modules, {"pip": pip, "pip._internal.utils.compatibility_tags": tags_module}
        ),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        exec(compile(probe, "candidate-probe", "exec"), {})
    report = json.loads(output.getvalue())
    assert report["pip_version"] == "22.3.1"
    assert report["pip_tag_inventory_available"] is (not inventory_error)
    if not inventory_error:
        assert report["pip_arm32_tags"] is True
        assert report["pip_arm64_tags"] is False
        assert report["pip_native_cpython_abi"] is True
    assert "PRIVATE" not in output.getvalue()
    assert not errors.getvalue()
