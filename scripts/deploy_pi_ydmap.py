"""GitHub-only, pinned-SSH entry point for the private Pi YDMap scraper."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import logging
import os
import re
import selectors
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pi_host/dsh_ydmap"
TEST_NAMES = ("pi_baoti_scraper_test.py", "pi_ydmap_identity_test.py")
MAX_REPORT_BYTES = 1_000_000
OPERATIONS = {"preflight", "apply", "health", "inspect"}
_contract_spec = importlib.util.spec_from_file_location("pi_ydmap_contract", SOURCE / "install.py")
assert _contract_spec is not None and _contract_spec.loader is not None
CONTRACT = importlib.util.module_from_spec(_contract_spec)
_contract_spec.loader.exec_module(CONTRACT)
FAILURES = {
    "command_failed",
    "invalid_report",
    "scraper_busy",
    "scrape_not_verified",
    "access_verification",
    "scraper_identity_mismatch",
    "date_identity_mismatch",
    "product_identity_mismatch",
    "invalid_court_identity",
    "unrecognized_scraper_service",
    "unrecognized_scraper_override",
    "scraper_drain_timeout",
    "invalid_candidate",
    "candidate_digest_mismatch",
    "candidate_tests_missing",
    "candidate_tests_failed",
    "candidate_start_failed",
    "installed_health_failed",
    "unrecognized_current_release",
    "activation_failed",
    "unrelated_service_changed",
    "root_required",
    "staging_required",
    "operation_failed",
    "dag_drain_proof_required",
    "dag_drain_proof_expired",
    "invalid_slot_identity",
    "operation_deadline",
    "operation_interrupted",
    "source_identity_mismatch",
    "report_too_large",
}

HOST_GUARD_LAUNCH = r"""
import os
import re
import subprocess
import sys

repo, source, commit, guard_id = sys.argv[1:]
try:
    candidates = subprocess.check_output(["docker", "ps", "--filter", "label=com.docker.compose.service=airflow-api-server", "--format", "{{.ID}}"], stderr=subprocess.DEVNULL, universal_newlines=True).splitlines()
    owned = []
    for candidate in candidates:
        if not re.fullmatch(r"[0-9a-f]{12,64}", candidate):
            raise ValueError()
        directory = subprocess.check_output(["docker", "inspect", "--format", '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}', candidate], stderr=subprocess.DEVNULL, universal_newlines=True).strip()
        if os.path.realpath(directory) == os.path.realpath(repo):
            owned.append(candidate)
    if len(owned) != 1:
        raise ValueError()
    os.execvp("docker", ["docker", "exec", "-i", owned[0], "python", "-u", "-c", source, "--target-commit", commit, "--guard-id", guard_id])
except Exception:
    print('{"event":"failed","ok":false,"errorClass":"AirflowContainerUnavailable"}', flush=True)
    sys.exit(1)
"""


class AirflowGuard:
    """Explicit completion releases early; disconnect preserves the bounded fence."""

    def __init__(self, commit: str):
        self.commit = commit
        self.guard_id = uuid.uuid4().hex
        self.process = None
        self.proof = None
        self.restored = False
        self.buffer = b""
        self.bytes_read = 0

    def _next_event(self, timeout: int) -> dict:
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                while b"\n" in self.buffer:
                    line, self.buffer = self.buffer.split(b"\n", 1)
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict) and value.get("event") in {
                            "drained",
                            "failed",
                            "restored",
                        }:
                            return value
                    except ValueError:
                        pass
                if not selector.select(min(1, max(0, deadline - time.monotonic()))):
                    continue
                data = os.read(self.process.stdout.fileno(), 8192)
                if not data:
                    raise RuntimeError("airflow_guard_disconnected")
                self.bytes_read += len(data)
                if self.bytes_read > 65536:
                    raise RuntimeError("airflow_guard_output_limit")
                self.buffer += data
        raise TimeoutError("airflow_guard_timeout")

    def __enter__(self):
        # Match the production Airflow SSH identity; never use a Pi password for this host.
        host = os.environ["AIRFLOW_SSH_HOST"]
        username = os.environ["AIRFLOW_SSH_USER"]
        port = int(os.environ["AIRFLOW_SSH_PORT"])
        repository = os.environ["AIRFLOW_REPOSITORY_PATH"]
        if not 1 <= port <= 65535 or not host or not username or not repository.startswith("/"):
            raise ValueError("invalid_airflow_remote")
        source = (ROOT / "scripts/pi_ydmap_dag_guard.py").read_text()
        remote_command = " ".join(
            shlex.quote(item)
            for item in (
                "python3",
                "-c",
                HOST_GUARD_LAUNCH,
                repository,
                source,
                self.commit,
                self.guard_id,
            )
        )
        self.process = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "PasswordAuthentication=no",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=15",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "ServerAliveCountMax=3",
                "-p",
                str(port),
                f"{username}@{host}",
                remote_command,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            event = self._next_event(660)
            if event.get("event") != "drained" or event.get("ok") is not True:
                raise RuntimeError("airflow_drain_failed")
            self.proof = CONTRACT.validate_drain_proof(event.get("proof"), self.commit)
            if self.proof["guard_id"] != self.guard_id:
                raise RuntimeError("airflow_guard_identity_mismatch")
            return self
        except Exception:
            self.close()
            raise

    def close(self, *, completed: bool = True):
        if self.process is None:
            return
        try:
            if self.process.stdin and not self.process.stdin.closed:
                if completed:
                    self.process.stdin.write(b"release\n")
                    self.process.stdin.flush()
                self.process.stdin.close()
        except (OSError, BrokenPipeError):
            pass
        if not completed:
            # The Pi may still be running. EOF keeps the remote guard paused
            # until its fixed deadline; never claim early restoration.
            self.process.terminate()
            self.process.wait(timeout=10)
            if self.process.stdout:
                self.process.stdout.close()
            return
        try:
            for _ in range(3):
                event = self._next_event(150)
                if event.get("event") == "restored":
                    self.restored = event.get("ok") is True and event.get("restored") is True
                    break
        except (OSError, RuntimeError, TimeoutError):
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.process.stdout:
            self.process.stdout.close()

    def __exit__(self, exc_type, exc, tb):
        self.close(completed=exc_type is None)
        if not self.restored:
            raise RuntimeError("airflow_pause_restore_not_verified")


def apply_with_guard(client, command: str, commit: str) -> dict:
    guard = AirflowGuard(commit)
    report = None
    try:
        with guard:
            report = remote(client, command, payload=guard.proof, timeout=1500)
    except Exception:
        return {
            "ok": False,
            "failure": "airflow_guard_or_operation_failed",
            "airflowPauseRestored": guard.restored,
            "airflowLeaseExpiresAt": guard.proof.get("expires_at") if guard.proof else None,
            "externalTestSends": 0,
            "scraperApplied": bool(report and report.get("applied")),
            "inspections": CONTRACT.safe_inspections(report.get("inspections", []))
            if report
            else [],
        }
    return {**report, "airflowPauseRestored": guard.restored, "airflowDrainVerified": True}


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        actual = "SHA256:" + base64.b64encode(
            hashlib.sha256(key.asbytes()).digest()
        ).decode().rstrip("=")
        expected = os.environ["PI_DEVICE_SSH_HOST_KEY_SHA256"].strip().rstrip("=")
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", expected) or not hmac.compare_digest(
            actual, expected
        ):
            raise paramiko.SSHException("host_key_mismatch")


def remote(
    client,
    command: str,
    *,
    payload: dict | None = None,
    timeout: int = 900,
    source_evidence: bool = False,
) -> dict:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if payload is not None:
        stdin.write(json.dumps(payload, ensure_ascii=False))
        stdin.flush()
    stdin.channel.shutdown_write()
    watchdog = threading.Timer(timeout, stdout.channel.close)
    watchdog.daemon = True
    watchdog.start()
    try:
        content = stdout.read(MAX_REPORT_BYTES + 1)
        stderr.read(MAX_REPORT_BYTES + 1)  # Never forward remote stderr or exception messages.
        status = stdout.channel.recv_exit_status()
    finally:
        watchdog.cancel()
    if len(content) > MAX_REPORT_BYTES:
        raise RuntimeError("invalid_remote_report")
    report = json.loads(content) if content.strip() else {}
    if not isinstance(report, dict) or status < 0 or report.get("operationComplete") is not True:
        raise RuntimeError("invalid_remote_report")
    if status:
        diagnostic = report.get("serviceDiagnostic")
        diagnostic_keys = {
            "active",
            "unprivilegedUser",
            "expectedInterpreter",
            "legacySourceMatched",
            "managedSourceMatched",
        }
        safe_diagnostic = (
            diagnostic
            if isinstance(diagnostic, dict)
            and set(diagnostic) == diagnostic_keys
            and all(type(value) is bool for value in diagnostic.values())
            else None
        )
        report = {
            "ok": False,
            "failure": report.get("failure")
            if report.get("failure") in FAILURES
            else "operation_failed",
            "rollbackVerified": report.get("rollbackVerified") is True,
            "venue": report.get("venue") if report.get("venue") in {"dsh", "baoti"} else None,
            "inspections": CONTRACT.safe_inspections(
                report.get("inspections", []), source_evidence=source_evidence
            ),
            "sourceEvidenceTruncated": report.get("sourceEvidenceTruncated") is True,
            "sourceEvidenceRejected": report.get("sourceEvidenceRejected") is True,
            "serviceDiagnostic": safe_diagnostic,
            "sourceFailure": CONTRACT.safe_source_failure(report.get("sourceFailure")),
            "sourceDiagnostic": CONTRACT.safe_source_diagnostic(report.get("sourceDiagnostic")),
            "externalTestSends": 0,
        }
    return json.loads(CONTRACT.encode_report(report, source_evidence=source_evidence))


def verify_checkout(commit: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid_commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()
    if head != commit:
        raise ValueError("checkout_mismatch")
    source = (SOURCE / "server.py").read_bytes()
    committed = subprocess.run(
        ["git", "show", f"{commit}:pi_host/dsh_ydmap/server.py"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    if source != committed:
        raise ValueError("source_not_committed")
    return hashlib.sha256(source).hexdigest()


def main() -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey())
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    staging = None
    try:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("protected_workflow_required")
        operation = os.environ["OPERATION"]
        commit = os.environ["TARGET_COMMIT"]
        if operation not in OPERATIONS:
            raise ValueError("invalid_operation")
        source_hash = verify_checkout(commit)
        client.connect(
            os.environ["PI_DEVICE_SSH_HOST"],
            port=int(os.environ["PI_DEVICE_SSH_PORT"]),
            username=os.environ["PI_DEVICE_SSH_USER"],
            password=os.environ["PI_DEVICE_SSH_PASSWORD"],
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
        staging = "/tmp/pi-ydmap-release-" + uuid.uuid4().hex
        stdin, stdout, stderr = client.exec_command(
            "mkdir -m 700 " + shlex.quote(staging), timeout=30
        )
        stdin.channel.shutdown_write()
        stdout.read(1024)
        stderr.read(1024)
        if stdout.channel.recv_exit_status():
            raise RuntimeError("staging_failed")
        with client.open_sftp() as sftp:
            sftp.put(str(SOURCE / "install.py"), staging + "/install.py")
            if operation in {"preflight", "apply"}:
                sftp.put(str(SOURCE / "server.py"), staging + "/server.py")
                for name in TEST_NAMES:
                    path = ROOT / "tests" / name
                    if path.is_file():
                        sftp.put(str(path), staging + "/" + name)
        command = (
            "sudo -n /usr/bin/python3 "
            + shlex.quote(staging + "/install.py")
            + " "
            + operation
            + " --commit "
            + commit
            + " --source-sha256 "
            + source_hash
            + " --staging "
            + shlex.quote(staging)
        )
        report = (
            apply_with_guard(client, command, commit)
            if operation == "apply"
            else remote(client, command, timeout=1100, source_evidence=operation == "preflight")
        )
        encoded = CONTRACT.encode_report(report, source_evidence=operation == "preflight")
        print(encoded)
        return 0 if json.loads(encoded).get("ok") is True else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "errorClass": type(exc).__name__,
                    "failure": "operation_failed",
                    "externalTestSends": 0,
                }
            )
        )
        return 1
    finally:
        if staging:
            try:
                stdin, stdout, stderr = client.exec_command(
                    "rm -rf -- " + shlex.quote(staging), timeout=30
                )
                stdin.channel.shutdown_write()
                stdout.read(1024)
                stderr.read(1024)
                stdout.channel.recv_exit_status()
            except Exception:
                pass
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
