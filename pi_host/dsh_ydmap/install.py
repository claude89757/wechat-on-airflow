"""Bounded Pi scraper rollout; only the dedicated scrape service is changed."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import pwd
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path("/opt/pi-ydmap-scraper")
RUNUSER = Path("/usr/sbin/runuser")
UNIT = "dsh-ydmap-scraper.service"
DROPIN = Path("/etc/systemd/system/dsh-ydmap-scraper.service.d/90-managed-release.conf")
OTHER_UNITS = (
    "wechat-sender.service",
    "zacks-agent.service",
    "cloudflared-dsh.service",
    "pi-appium-mcp.service",
    "cloudflared-appium-mcp.service",
)
TEST_NAMES = ("pi_baoti_scraper_test.py", "pi_ydmap_identity_test.py")
MAX_BYTES = 1_000_000
MAX_SOURCE_EVIDENCE_BYTES = 128 * 1024
RENDERER_METHODS = {
    "isAvailableStatic",
    "textFun",
    "isNoBook",
    "classObj",
    "closeMsg",
    "sellerMessage",
    "isTicketDisabled",
}
SOURCE_CLASSES = {
    "col-inprocess",
    "col-completed",
    "col-locked",
    "col-scheduled",
    "orderNoBook",
    "expired",
    "noOpen",
    "disabled",
    "not-open",
    "col-fight-ing",
    "col-fight-request",
    "col-fight-respond",
    "fight-request",
    "fight-request-ing",
    "fight-respond",
    "col-max-ball",
    "col-ball",
    "selected",
}
SOURCE_LITERAL_ALLOWLIST = SOURCE_CLASSES | {
    "",
    " ",
    "/",
    "-",
    ":",
    "(",
    ")",
    "元",
    "分钟",
    "免费",
    "预订中",
    "已预订",
    "已过期",
    "已占用",
    "约战中",
    "已约战",
    "已应战",
    "未开放",
    "不可预约",
    "已售罄",
    "剩余",
    "可约",
    "undefined",
    "object",
    "function",
    "string",
    "number",
    "boolean",
    "length",
    "row",
    "price",
    "platformInfo",
    "venueName",
    "orderInfo",
    "className",
    "onlineBooking",
    "salesItemId",
    "open",
    "closed",
    "enabled",
    "disabled",
    "[redacted]",
    "[redacted template]",
    "[redacted regex]",
}
SOURCE_STRING = re.compile(r'"(?:[^"\\\r\n]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"')
PUBLIC_TEXT = re.compile(r"[\w\u3400-\u9fff ·.()（）-]{1,120}")
MARKER = "# Managed Pi YDMap release\n"
DAG_IDS = ("大沙河国际网球中心巡检", "宝安网球中心巡检")
LEASE_SECONDS = 1620
PROOF_MARGIN_SECONDS = 90
ACTIVATION_SECONDS = 540
ROLLBACK_SECONDS = 150
ACTIVATION_LEASE_REQUIRED = ACTIVATION_SECONDS + ROLLBACK_SECONDS + 60
SOURCE_FAILURES = {
    "captcha",
    "rate_limited",
    "login_required",
    "busy",
    "schedule_not_ready",
    "venue_host_mismatch",
    "venue_id_mismatch",
    "product_id_mismatch",
    "product_name_unverified",
    "product_name_mismatch",
    "date_identity_mismatch",
    "date_not_selected",
    "schedule_loading",
    "source_identity_unavailable",
    "source_not_refreshed",
    "court_identity_unavailable",
    "court_group_mismatch",
    "schedule_timeout",
    "refresh_date_unavailable",
    "requested_date_unavailable",
    "date_tab_not_found",
    "TimeoutError",
    "TimeoutException",
    "WebDriverException",
    "InvalidSessionIdException",
    "NoSuchWindowException",
    "ConnectionError",
}
SOURCE_FIELDS = {
    "challengeText",
    "challengeMaskVisible",
    "documentComplete",
    "scheduleComponentPresent",
    "pageHost",
    "selectedDate",
    "queryDate",
    "selectedSalesId",
    "sourceSalesId",
    "selectedProduct",
    "sourceProduct",
    "productName",
    "productNameField",
    "productInCatalog",
    "loadingCounter",
    "loadGeneration",
    "dataVersion",
    "courtNames",
    "cellCount",
}
PRODUCTS = {
    "dsh": {"": ("100000", "")},
    "baoti": {
        "outdoor": ("111317", "室外"),
        "indoor": ("103224", "室内"),
        "windrain": ("111319", "风雨"),
    },
}
ERROR_CLASSES = {
    "OperationFailure",
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "FileExistsError",
    "NotADirectoryError",
    "IsADirectoryError",
    "TimeoutError",
    "ConnectionError",
    "ConnectionRefusedError",
    "ConnectionResetError",
    "BrokenPipeError",
    "URLError",
    "HTTPError",
    "JSONDecodeError",
    "UnicodeDecodeError",
    "TypeError",
    "ValueError",
    "KeyError",
    "AttributeError",
    "IndexError",
    "RuntimeError",
    "TimeoutExpired",
    "CalledProcessError",
    "EOFError",
    "SSHException",
    "AuthenticationException",
    "BadHostKeyException",
    "NoValidConnectionsError",
}
FAILURE_PHASES = {
    "main": "operation_setup",
    "other_service_identities": "service_snapshot",
    "verify_existing_service": "existing_service_verification",
    "prepare_candidate": "candidate_prepare",
    "isolated_candidate": "candidate_runtime",
    "inspect_venues": "venue_inspection",
    "activate": "activation",
    "verify_checkout": "checkout_verification",
    "remote": "remote_operation",
    "apply_with_guard": "airflow_drain",
}
FAILURE_FUNCTIONS = set(FAILURE_PHASES) | {
    "operate",
    "service_properties",
    "request_json",
    "checked_runuser",
    "inspect_evidence",
    "verify_health",
    "wait_idle",
    "active_connections",
    "wait_health",
    "validate_drain_proof",
    "run",
    "digest",
    "atomic_bytes",
    "atomic_link",
    "encode_report",
}


def safe_error_class(value: object) -> str:
    return value if isinstance(value, str) and value in ERROR_CLASSES else "Exception"


def safe_failure_diagnostic(value: object) -> dict | None:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("phase"), str)
        or value.get("phase") not in set(FAILURE_PHASES.values())
        or not isinstance(value.get("function"), str)
        or value.get("function") not in FAILURE_FUNCTIONS
        or type(value.get("line")) is not int
        or not 1 <= value["line"] <= 100000
    ):
        return None
    return {key: value[key] for key in ("phase", "function", "line")}


def failure_details(exc: Exception, *, source_file: str = __file__) -> dict:
    # Only named functions/lines from our exact source; never messages, paths or locals.
    phase = "operation_setup"
    location = None
    trace = exc.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        if code.co_filename == source_file and code.co_name in FAILURE_FUNCTIONS:
            if phase == "operation_setup" and code.co_name != "main":
                phase = FAILURE_PHASES.get(code.co_name, phase)
            location = {"phase": phase, "function": code.co_name, "line": trace.tb_lineno}
        trace = trace.tb_next
    return {
        "errorClass": safe_error_class(type(exc).__name__),
        "failureDiagnostic": safe_failure_diagnostic(location),
    }


class OperationFailure(RuntimeError):
    def __init__(self, code: str, *, rollback_verified: bool = False):
        super().__init__(code)
        self.code = code
        self.rollback_verified = rollback_verified
        self.venue = None
        self.inspections = []
        self.service_diagnostic = None
        self.source_failure = None
        self.source_diagnostic = {}


def safe_source_failure(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"date_tab_not_found:\d{4}-\d{2}-\d{2}", value):
        return "date_tab_not_found"
    return value if value in SOURCE_FAILURES else None


def safe_source_diagnostic(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {}
    # Presence alone is useful when a provider changed field types. No unknown
    # string, URL, cookie, body fragment or error message is forwarded.
    present = value.get("present", {})
    result["present"] = {
        key: key in value or (isinstance(present, dict) and present.get(key) is True)
        for key in sorted(SOURCE_FIELDS)
    }
    for key in ("selectedDate", "queryDate"):
        candidate = value.get(key)
        try:
            if (
                isinstance(candidate, str)
                and date.fromisoformat(candidate).isoformat() == candidate
            ):
                result[key] = candidate
        except ValueError:
            pass
    for key in ("selectedSalesId", "sourceSalesId", "selectedProduct", "sourceProduct"):
        candidate = value.get(key)
        if isinstance(candidate, str) and re.fullmatch(r"[0-9]{1,12}", candidate):
            result[key] = candidate
    for key in ("loadingCounter", "loadGeneration", "cellCount"):
        candidate = value.get(key)
        if type(candidate) is int and 0 <= candidate <= 1_000_000:
            result[key] = candidate
    if value.get("pageHost") in {"wxsports.ydmap.cn", "bawtt.ydmap.cn"}:
        result["pageHost"] = value["pageHost"]
    if value.get("productNameField") in {"salesItemName", "itemName", "name"}:
        result["productNameField"] = value["productNameField"]
    for key in (
        "productInCatalog",
        "challengeText",
        "challengeMaskVisible",
        "documentComplete",
        "scheduleComponentPresent",
    ):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    product_name = value.get("productName")
    if isinstance(product_name, str) and PUBLIC_TEXT.fullmatch(product_name):
        result["productName"] = product_name
    names = value.get("courtNames")
    if (
        isinstance(names, list)
        and len(names) <= 100
        and all(isinstance(name, str) and PUBLIC_TEXT.fullmatch(name) for name in names)
    ):
        result["courtNames"] = names
    versions = value.get("dataVersion")
    if isinstance(versions, dict):
        result["dataVersion"] = {
            key: versions[key]
            for key in ("platforms", "orders")
            if type(versions.get(key)) is int and 0 <= versions[key] <= 1_000_000
        }
    return result


def _bounded_int(value: object, maximum: int = 1_000_000) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _public_clock(value: object, *, end: bool = False) -> bool:
    return isinstance(value, str) and (
        bool(re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value)) or (end and value == "24:00")
    )


def _safe_renderer_source(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        if len(value.encode("utf-8")) > 4096:
            return False
        for literal in SOURCE_STRING.findall(value):
            decoded = json.loads(literal)
            if decoded not in SOURCE_LITERAL_ALLOWLIST and not re.fullmatch(r"\d{1,3}", decoded):
                return False
    except (ValueError, UnicodeError):
        return False
    outside = SOURCE_STRING.sub("", value)
    return not (
        any(marker in outside for marker in ("'", '"', "`", "//", "/*", "*/"))
        or re.search(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f]|[0-9]{7,}|[A-Za-z_$][A-Za-z0-9_$]{64,}", outside
        )
        or any(
            len(number) > 6
            for number in re.findall(
                r"(?<![\w$])(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", outside
            )
        )
    )


def safe_source_evidence(value: object, *, cell_count: int) -> dict | None:
    try:
        return _parse_source_evidence(value, cell_count=cell_count)
    except (TypeError, ValueError, UnicodeError, OverflowError):
        return None


def _parse_source_evidence(value: object, *, cell_count: int) -> dict | None:
    """Keep diagnostic facts only; this never certifies booking classification."""
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or value.get("bookability_verified") is not False
    ):
        return None
    counts = ("source_cell_count", "matched_cell_count", "unmatched_cell_count")
    flags = ("coverage_complete", "component_scan_truncated", "source_truncated")
    if any(not _bounded_int(value.get(key), 100000) for key in counts) or any(
        type(value.get(key)) is not bool for key in flags
    ):
        return None
    if (
        value["source_cell_count"] != cell_count
        or value["matched_cell_count"] + value["unmatched_cell_count"] != cell_count
        or (
            value["coverage_complete"]
            and (value["unmatched_cell_count"] or value["component_scan_truncated"])
        )
    ):
        return None
    components, methods, samples = (value.get(key) for key in ("components", "methods", "samples"))
    if (
        not isinstance(components, list)
        or len(components) > 16
        or not isinstance(methods, list)
        or len(methods) > 24
        or not isinstance(samples, list)
        or len(samples) > 2
    ):
        return None
    safe_components, indices = [], set()
    for component in components:
        if (
            not isinstance(component, dict)
            or not _bounded_int(component.get("index"), 15)
            or component["index"] in indices
            or not _bounded_int(component.get("matched_cell_count"), cell_count)
        ):
            return None
        name = component.get("name")
        present = component.get("methods")
        if name is not None and (
            not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
        ):
            return None
        if not isinstance(present, dict) or any(
            type(present.get(key)) is not bool for key in RENDERER_METHODS
        ):
            return None
        indices.add(component["index"])
        safe_components.append(
            {
                "index": component["index"],
                "name": name,
                "matched_cell_count": component["matched_cell_count"],
                "methods": {key: present[key] for key in sorted(RENDERER_METHODS)},
            }
        )
    safe_methods = []
    for method in methods:
        if (
            not isinstance(method, dict)
            or method.get("name") not in RENDERER_METHODS
            or method.get("kind") not in {"method", "computed"}
        ):
            return None
        refs, source, sha = (method.get(key) for key in ("component_indices", "source", "sha256"))
        if (
            not isinstance(refs, list)
            or not 1 <= len(refs) <= 16
            or any(type(ref) is not int or ref not in indices for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            return None
        if (
            not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-f]{64}", sha)
            or not _safe_renderer_source(source)
        ):
            return None
        if (
            any(type(method.get(key)) is not bool for key in ("truncated", "redacted", "reused"))
            or not _bounded_int(method.get("original_bytes"))
            or not _bounded_int(method.get("emitted_bytes"), 4096)
        ):
            return None
        if method["emitted_bytes"] != len(source.encode("utf-8")):
            return None
        if method["truncated"] and not value["source_truncated"]:
            return None
        if method["reused"]:
            if source or method["emitted_bytes"]:
                return None
        elif (not source and not method["truncated"]) or hashlib.sha256(
            source.encode("utf-8")
        ).hexdigest() != sha:
            return None
        safe_methods.append(
            {
                "component_indices": refs,
                "name": method["name"],
                "kind": method["kind"],
                "sha256": sha,
                "source": source,
                **{
                    key: method[key]
                    for key in (
                        "original_bytes",
                        "emitted_bytes",
                        "truncated",
                        "redacted",
                        "reused",
                    )
                },
            }
        )
    safe_samples = []
    sample_flags = (
        "included",
        "expired",
        "order_no_book",
        "has_order",
        "has_price",
        "online_booking_redacted",
    )
    for sample in samples:
        if not isinstance(sample, dict) or any(
            type(sample.get(key)) is not bool for key in sample_flags
        ):
            return None
        court, start, end, classes = (
            sample.get(key) for key in ("court", "start", "end", "known_classes")
        )
        if (
            not isinstance(court, str)
            or not PUBLIC_TEXT.fullmatch(court)
            or not _public_clock(start)
            or not _public_clock(end, end=True)
            or start >= end
        ):
            return None
        if (
            not isinstance(classes, list)
            or len(classes) > len(SOURCE_CLASSES)
            or any(not isinstance(item, str) or item not in SOURCE_CLASSES for item in classes)
            or len(set(classes)) != len(classes)
        ):
            return None
        online = sample.get("online_booking")
        online_ok = online is None or type(online) is bool
        if type(online) in (int, float):
            online_ok = math.isfinite(online) and abs(online) <= 1000
        elif isinstance(online, str):
            online_ok = online.lower() in {"open", "closed", "enabled", "disabled"} and online in {
                online.lower(),
                online.upper(),
                online.title(),
            }
            online_ok = (
                online_ok
                or online in {"开放", "关闭", "开启", "不开放"}
                or bool(re.fullmatch(r"-?\d{1,3}(?:\.\d{1,3})?", online))
            )
        if not online_ok:
            return None
        safe_samples.append(
            {
                "court": court,
                "start": start,
                "end": end,
                "known_classes": classes,
                "online_booking": online,
                **{key: sample[key] for key in sample_flags},
            }
        )
    return {
        "schema_version": 1,
        "bookability_verified": False,
        **{key: value[key] for key in (*counts, *flags)},
        "components": safe_components,
        "methods": safe_methods,
        "samples": safe_samples,
    }


def limit_source_evidence(inspections: list[dict]) -> tuple[bool, bool]:
    """Bound optional diagnostics without changing any verified identity record."""
    budget = MAX_SOURCE_EVIDENCE_BYTES
    truncated = any(report.get("sourceEvidenceTruncated") is True for report in inspections)
    rejected = any(report.get("sourceEvidenceRejected") is True for report in inspections)
    entries = []
    for report in inspections:
        for day in report["days"]:
            for group in day["groups"]:
                if "source_evidence" not in group:
                    continue
                evidence = group["source_evidence"]
                truncated = (
                    truncated
                    or evidence["source_truncated"]
                    or evidence["component_scan_truncated"]
                )
                size = len(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8"))
                if size > budget:
                    del group["source_evidence"]
                    truncated = True
                    continue
                budget -= size
                entries.append(group)
    # Source may appear in a later date because the scraper refreshes tomorrow
    # before today. Resolve references after reading the whole bounded result.
    changed = True
    while changed:
        changed = False
        available = {
            (method["name"], method["sha256"])
            for group in entries
            if "source_evidence" in group
            for method in group["source_evidence"]["methods"]
            if not method["reused"]
        }
        for group in entries:
            evidence = group.get("source_evidence")
            if evidence is not None and any(
                method["reused"] and (method["name"], method["sha256"]) not in available
                for method in evidence["methods"]
            ):
                del group["source_evidence"]
                rejected = True
                changed = True
    return truncated, rejected


def encode_report(report: dict, *, source_evidence: bool = False) -> str:
    """Validate both success/failure evidence and enforce the whole JSON budget."""
    bounded = dict(report)
    if not source_evidence:
        bounded.pop("sourceEvidenceTruncated", None)
        bounded.pop("sourceEvidenceRejected", None)
    if "inspections" in bounded:
        bounded["inspections"] = safe_inspections(
            bounded["inspections"], source_evidence=source_evidence
        )
        if source_evidence:
            truncated, rejected = limit_source_evidence(bounded["inspections"])
            bounded["sourceEvidenceTruncated"] = (
                truncated or bounded.get("sourceEvidenceTruncated") is True
            )
            bounded["sourceEvidenceRejected"] = (
                rejected or bounded.get("sourceEvidenceRejected") is True
            )
    encoded = json.dumps(bounded, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) + 1 >= MAX_BYTES:
        encoded = json.dumps(
            {
                "ok": False,
                "operationComplete": bounded.get("operationComplete") is True,
                "failure": "report_too_large",
                "applied": bounded.get("applied") is True,
                "rollbackVerified": bounded.get("rollbackVerified") is True,
                "externalTestSends": 0,
                "sourceEvidenceTruncated": True,
            },
            sort_keys=True,
        )
    return encoded


@contextlib.contextmanager
def bounded_action(seconds: int, *, rollback: bool = False):
    def expired(signum, frame):
        raise OperationFailure("operation_deadline")

    previous = signal.signal(signal.SIGALRM, expired)
    previous_interrupts = {}
    if rollback:
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            previous_interrupts[signum] = signal.signal(signum, signal.SIG_IGN)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        for signum, handler in previous_interrupts.items():
            signal.signal(signum, handler)


def run(argv: list[str], *, timeout: int = 30) -> str:
    result = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    if result.returncode or len(result.stdout) > MAX_BYTES:
        raise OperationFailure("command_failed")
    return result.stdout.decode("utf-8")


def checked_runuser() -> str:
    if not RUNUSER.is_file() or not os.access(RUNUSER, os.X_OK):
        raise OperationFailure("runuser_unavailable")
    return str(RUNUSER)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_bytes(path: Path, value: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".ydmap-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_link(target: Path, path: Path) -> None:
    temporary = path.with_name(path.name + ".next")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target)
    os.replace(temporary, path)


def request_json(port: int, path: str, *, timeout: int = 5) -> dict:
    # Private service only: no cookies, credentials, upstream request replay or redirects.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
            content = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        failure = OperationFailure("scraper_busy" if exc.code == 429 else "scrape_not_verified")
        try:
            failed_payload = json.loads(exc.read(MAX_BYTES + 1))
            if isinstance(failed_payload, dict):
                if failed_payload.get("captcha") is True:
                    failure = OperationFailure("access_verification")
                failure.source_failure = safe_source_failure(failed_payload.get("error"))
                failure.source_diagnostic = safe_source_diagnostic(
                    failed_payload.get("diagnostics")
                )
        except (ValueError, OSError):
            pass
        raise failure from None
    if len(content) > MAX_BYTES:
        raise OperationFailure("invalid_report")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise OperationFailure("invalid_report")
    return value


def verify_health(payload: dict, commit: str, source_hash: str) -> dict:
    if (
        payload.get("ok") is not True
        or payload.get("service") != "dsh_ydmap"
        or payload.get("protocolVersion") != 2
        or payload.get("deploymentCommit") != commit
        or payload.get("sourceSha256") != source_hash
        or sorted(payload.get("venues", [])) != ["baoti", "dsh"]
    ):
        raise OperationFailure("scraper_identity_mismatch")
    return {
        "protocolVersion": 2,
        "deploymentCommit": commit,
        "sourceSha256": source_hash,
        "venues": ["baoti", "dsh"],
    }


def public_names(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 100
        or any(not isinstance(name, str) or not PUBLIC_TEXT.fullmatch(name) for name in value)
    ):
        raise OperationFailure("invalid_court_identity")
    return value


def validate_drain_proof(value: object, commit: str, *, remaining: int = 30) -> dict:
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("target_commit") != commit
        or value.get("drained") is not True
    ):
        raise OperationFailure("dag_drain_proof_required")
    if not isinstance(value.get("guard_id"), str) or not re.fullmatch(
        r"[0-9a-f]{32}", value["guard_id"]
    ):
        raise OperationFailure("dag_drain_proof_required")
    if (
        type(value.get("issued_at")) is not int
        or type(value.get("expires_at")) is not int
        or value["expires_at"] - value["issued_at"] != LEASE_SECONDS - PROOF_MARGIN_SECONDS
        # A slow Pi clock could otherwise overestimate the lease. Faster clocks
        # only shorten it; the 90-second remote fence absorbs <=30s slow skew.
        or value["issued_at"] > time.time() + 30
        or not time.time() + remaining < value["expires_at"] <= time.time() + LEASE_SECONDS
    ):
        raise OperationFailure("dag_drain_proof_expired")
    if (
        type(value.get("active_tasks")) is not int
        or value["active_tasks"] != 0
        or type(value.get("active_runs")) is not int
        or value["active_runs"] != 0
    ):
        raise OperationFailure("dag_drain_proof_required")
    dags = value.get("dags")
    if not isinstance(dags, list) or not 1 <= len(dags) <= 2:
        raise OperationFailure("dag_drain_proof_required")
    if any(
        not isinstance(dag, dict)
        or dag.get("dag_id") not in DAG_IDS
        or dag.get("paused") is not True
        or type(dag.get("was_paused")) is not bool
        for dag in dags
    ):
        raise OperationFailure("dag_drain_proof_required")
    if len({dag["dag_id"] for dag in dags}) != len(dags) or DAG_IDS[0] not in {
        dag["dag_id"] for dag in dags
    }:
        raise OperationFailure("dag_drain_proof_required")
    return value


def validate_slots(courts: object, known_names: set[str]) -> tuple[int, int]:
    if not isinstance(courts, dict) or len(courts) > 100 or not set(courts).issubset(known_names):
        raise OperationFailure("invalid_slot_identity")
    total = 0
    for name, ranges in courts.items():
        public_names([name])
        if not isinstance(ranges, list) or len(ranges) > 1000:
            raise OperationFailure("invalid_slot_identity")
        for pair in ranges:
            if not isinstance(pair, list) or len(pair) != 2:
                raise OperationFailure("invalid_slot_identity")
            for index, value in enumerate(pair):
                if not isinstance(value, str) or not re.fullmatch(r"\d{2}:\d{2}", value):
                    raise OperationFailure("invalid_slot_identity")
                hours, minutes = (int(part) for part in value.split(":"))
                if not (0 <= hours <= 23 and 0 <= minutes <= 59) and not (
                    index == 1 and value == "24:00"
                ):
                    raise OperationFailure("invalid_slot_identity")
            if pair[0] >= pair[1]:
                raise OperationFailure("invalid_slot_identity")
            total += 1
    return len(courts), total


def inspect_evidence(
    payload: dict, venue: str, expected_dates: list[str], *, source_evidence: bool = False
) -> dict:
    if (
        payload.get("ok") is not True
        or payload.get("captcha") is not False
        or payload.get("schema_version") != 2
        or payload.get("venue") != venue
        or not isinstance(payload.get("days"), list)
    ):
        raise OperationFailure("scrape_not_verified")
    expected = PRODUCTS[venue]
    expected_products = {item[0] for item in expected.values()}
    expected_keys = set(expected)
    days = payload["days"]
    if not 1 <= len(days) <= 7 or any(
        date.fromisoformat(value).isoformat() != value for value in expected_dates
    ):
        raise OperationFailure("date_identity_mismatch")
    if [day.get("date") for day in days if isinstance(day, dict)] != expected_dates:
        raise OperationFailure("date_identity_mismatch")
    report_days = []
    rejected_source = False
    for day in days:
        groups = day.get("groups")
        if not isinstance(groups, list) or len(groups) != len(expected_products):
            raise OperationFailure("product_identity_mismatch")
        if any(not isinstance(group, dict) for group in groups):
            raise OperationFailure("product_identity_mismatch")
        if {str(group.get("sales_item_id")) for group in groups} != expected_products or {
            group.get("key") for group in groups
        } != expected_keys:
            raise OperationFailure("product_identity_mismatch")
        safe_groups = []
        known_names = set()
        for group in groups:
            if group.get("source_date") != day["date"] or group.get("selected_date") != day["date"]:
                raise OperationFailure("date_identity_mismatch")
            count = group.get("cell_count")
            if type(count) is not int or not 0 < count <= 100000:
                raise OperationFailure("invalid_court_identity")
            product_id, label = expected[group["key"]]
            product_name = public_names([group.get("product_name")])[0]
            if str(group.get("sales_item_id")) != product_id or (
                label and label not in product_name
            ):
                raise OperationFailure("product_identity_mismatch")
            expected_host, expected_sales = (
                ("wxsports.ydmap.cn", "100220") if venue == "dsh" else ("bawtt.ydmap.cn", "104036")
            )
            if (
                group.get("source_host") != expected_host
                or str(group.get("source_sales_id")) != expected_sales
            ):
                raise OperationFailure("product_identity_mismatch")
            generation = group.get("load_generation")
            versions = group.get("data_version")
            freshness = "both_source_arrays_replaced_after_date_selection"
            if (
                group.get("freshness") != freshness
                or type(generation) is not int
                or not 1 <= generation <= 1_000_000
                or not isinstance(versions, dict)
                or any(
                    type(versions.get(key)) is not int or not 1 <= versions[key] <= 1_000_000
                    for key in ("platforms", "orders")
                )
            ):
                raise OperationFailure("source_identity_mismatch")
            entry = {
                "key": group["key"],
                "sales_item_id": str(group["sales_item_id"]),
                "source_date": day["date"],
                "selected_date": day["date"],
                "court_names": public_names(group.get("court_names")),
                "cell_count": count,
                "product_name": product_name,
                "source_host": expected_host,
                "source_sales_id": expected_sales,
                "load_generation": generation,
                "data_version": {key: versions[key] for key in ("platforms", "orders")},
                "freshness": freshness,
            }
            if source_evidence and "source_evidence" in group:
                optional = safe_source_evidence(group["source_evidence"], cell_count=count)
                if optional is None:
                    rejected_source = True
                else:
                    entry["source_evidence"] = optional
            known_names.update(entry["court_names"])
            safe_groups.append(entry)
        courts = day.get("courts")
        court_count, slot_count = validate_slots(courts, known_names)
        report_days.append(
            {
                "date": day["date"],
                "groups": safe_groups,
                "availableCourtCount": court_count,
                "slotCount": slot_count,
            }
        )
    report = {"venue": venue, "verified": True, "days": report_days}
    if source_evidence:
        truncated, unresolved = limit_source_evidence([report])
        report["sourceEvidenceTruncated"] = truncated
        report["sourceEvidenceRejected"] = rejected_source or unresolved
    return report


def safe_inspections(value: object, *, source_evidence: bool = False) -> list[dict]:
    if not isinstance(value, list) or len(value) > 2:
        return []
    result = []
    try:
        for report in value:
            if (
                not isinstance(report, dict)
                or report.get("verified") is not True
                or report.get("venue") not in PRODUCTS
            ):
                return []
            days = report.get("days")
            if not isinstance(days, list) or not 1 <= len(days) <= 7:
                return []
            raw = {
                "ok": True,
                "captcha": False,
                "schema_version": 2,
                "venue": report["venue"],
                "days": [
                    {"date": day["date"], "groups": day["groups"], "courts": {}} for day in days
                ],
            }
            safe = inspect_evidence(
                raw, report["venue"], [day["date"] for day in days], source_evidence=source_evidence
            )
            if source_evidence:
                for key in ("sourceEvidenceTruncated", "sourceEvidenceRejected"):
                    safe[key] = safe.get(key) is True or report.get(key) is True
            for source, target in zip(days, safe["days"], strict=True):
                for key, maximum in (("availableCourtCount", 100), ("slotCount", 100000)):
                    count = source.get(key)
                    if type(count) is not int or not 0 <= count <= maximum:
                        return []
                    target[key] = count
            result.append(safe)
    except (KeyError, TypeError, ValueError, OperationFailure):
        return []
    return result


def inspect_venues(
    port: int, *, at: datetime | None = None, source_evidence: bool = False
) -> list[dict]:
    reports = []
    local = at or datetime.now(ZoneInfo("Asia/Shanghai"))
    for venue, days, timeout in (("dsh", 5 if local.hour >= 12 else 4, 150), ("baoti", 2, 240)):
        today = local.date()
        expected = [(today + timedelta(days=offset)).isoformat() for offset in range(days)]
        try:
            path = f"/inspect?venue={venue}&days={days}"
            if source_evidence:
                path += "&evidence=source-v1"
            payload = request_json(port, path, timeout=timeout)
            reports.append(
                inspect_evidence(payload, venue, expected, source_evidence=source_evidence)
            )
        except OperationFailure as exc:
            exc.venue = venue
            exc.inspections = reports
            raise
    return reports


def service_properties(unit: str) -> dict[str, str]:
    result = run(
        [
            "systemctl",
            "show",
            unit,
            "--property=ActiveState,MainPID,ExecMainStartTimestampMonotonic,User,ExecStart",
        ]
    )
    return dict(line.split("=", 1) for line in result.splitlines() if "=" in line)


def other_service_identities() -> dict[str, tuple[str, str, str]]:
    result = {}
    for unit in OTHER_UNITS:
        properties = service_properties(unit)
        result[unit] = tuple(
            properties.get(key, "")
            for key in ("ActiveState", "MainPID", "ExecMainStartTimestampMonotonic")
        )
    return result


def verify_existing_service() -> pwd.struct_passwd:
    properties = service_properties(UNIT)
    username = properties.get("User", "")
    diagnostic = {
        "active": properties.get("ActiveState") == "active",
        "unprivilegedUser": bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username))
        and username != "root",
        "expectedInterpreter": "path=/usr/bin/python3 " in properties.get("ExecStart", ""),
        "legacySourceMatched": False,
        "managedSourceMatched": False,
    }
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", username) or username == "root":
        failure = OperationFailure("unrecognized_scraper_service")
        failure.service_diagnostic = diagnostic
        raise failure
    account = pwd.getpwnam(username)
    command = properties.get("ExecStart", "")
    legacy = f"/home/{username}/dsh_ydmap/server.py"
    managed = str(BASE / "current/server.py")
    diagnostic["legacySourceMatched"] = bool(
        re.search(r"/usr/bin/python3 " + re.escape(legacy) + r"(?:\s|;|$)", command)
    )
    diagnostic["managedSourceMatched"] = bool(
        re.search(r"/usr/bin/python3 " + re.escape(managed) + r"(?:\s|;|$)", command)
    )
    if not diagnostic["active"] or not (
        diagnostic["legacySourceMatched"] or diagnostic["managedSourceMatched"]
    ):
        failure = OperationFailure("unrecognized_scraper_service")
        failure.service_diagnostic = diagnostic
        raise failure
    if DROPIN.exists() and not DROPIN.read_text().startswith(MARKER):
        raise OperationFailure("unrecognized_scraper_override")
    request_json(8788, "/healthz")
    return account


def active_connections(port: int) -> int:
    # Accept no active HTTP clients before replacing the dedicated listener.
    count = 0
    for path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        if not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            fields = line.split()
            if (
                len(fields) > 3
                and int(fields[1].rsplit(":", 1)[1], 16) == port
                and fields[3] == "01"
            ):
                count += 1
    return count


def wait_idle() -> None:
    deadline = time.monotonic() + 240
    idle_count = 0
    while time.monotonic() < deadline:
        health = request_json(8788, "/healthz")
        idle = health.get("busy") is not True and active_connections(8788) == 0
        idle_count = idle_count + 1 if idle else 0
        if idle_count >= 2:
            return
        time.sleep(2)
    raise OperationFailure("scraper_drain_timeout")


def prepare_candidate(
    staging: Path, commit: str, source_hash: str, account: pwd.struct_passwd
) -> Path:
    source = staging / "server.py"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise OperationFailure("invalid_candidate")
    if digest(source) != source_hash:
        raise OperationFailure("candidate_digest_mismatch")
    BASE.mkdir(mode=0o755, exist_ok=True)
    BASE.chmod(0o755)
    releases = BASE / "releases"
    releases.mkdir(mode=0o755, exist_ok=True)
    releases.chmod(0o755)
    candidate = Path(tempfile.mkdtemp(prefix=commit[:12] + "-", dir=releases))
    candidate.chmod(0o755)
    server = candidate / "pi_host/dsh_ydmap/server.py"
    server.parent.mkdir(parents=True)
    (candidate / "pi_host").chmod(0o755)
    server.parent.chmod(0o755)
    shutil.copyfile(source, server)
    server.chmod(0o644)
    tests = candidate / "tests"
    tests.mkdir()
    tests.chmod(0o755)
    for name in TEST_NAMES:
        test = staging / name
        if test.exists():
            if test.is_symlink() or test.stat().st_size > MAX_BYTES:
                raise OperationFailure("invalid_candidate")
            shutil.copyfile(test, tests / name)
            (tests / name).chmod(0o644)
    if not (tests / TEST_NAMES[0]).is_file():
        raise OperationFailure("candidate_tests_missing")
    run(["/usr/bin/python3", "-m", "py_compile", str(server)])
    result = subprocess.run(
        [
            checked_runuser(),
            "-u",
            account.pw_name,
            "--",
            "/usr/bin/python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            str(tests),
            "-p",
            "pi_*test.py",
        ],
        capture_output=True,
        timeout=60,
        check=False,
    )
    summary = re.search(rb"Ran (\d+) tests? in", result.stderr)
    passed = result.returncode == 0 and summary is not None and int(summary[1]) > 0
    atomic_bytes(
        candidate / "verification.json",
        json.dumps(
            {"mockTestsPassed": passed, "testCount": int(summary[1]) if summary else 0}
        ).encode(),
    )
    if not passed:
        raise OperationFailure("candidate_tests_failed")
    atomic_bytes(
        candidate / "release.json",
        json.dumps({"commit": commit, "sourceSha256": source_hash}).encode(),
    )
    return candidate


@contextlib.contextmanager
def isolated_candidate(candidate: Path, account: pwd.struct_passwd, commit: str):
    executable = checked_runuser()
    runtime = Path(tempfile.mkdtemp(prefix="pi-ydmap-candidate-"))
    os.chown(runtime, account.pw_uid, account.pw_gid)
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": account.pw_dir,
        "DISPLAY": ":0",
        "XAUTHORITY": str(Path(account.pw_dir) / ".Xauthority"),
        "XDG_RUNTIME_DIR": f"/run/user/{account.pw_uid}",
        "YDMAP_LISTEN_PORT": "18788",
        "YDMAP_DEBUG_PORT": "19224",
        "YDMAP_PROFILE": str(runtime / "profile"),
        "YDMAP_DEPLOYMENT_COMMIT": commit,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    process = None
    try:
        process = subprocess.Popen(
            [
                executable,
                "-u",
                account.pw_name,
                "--",
                "/usr/bin/python3",
                str(candidate / "pi_host/dsh_ydmap/server.py"),
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise OperationFailure("candidate_start_failed")
            try:
                request_json(18788, "/healthz")
                break
            except OSError:
                time.sleep(1)
        else:
            raise OperationFailure("candidate_start_failed")
        yield 18788
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        if process is not None:
            subprocess.run(
                [
                    "pkill",
                    "-TERM",
                    "-f",
                    r"^/usr/lib/chromium/chromium .*--remote-debugging-port=19224( |$)",
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
        # Only this candidate's directory is removed; active and legacy profiles are untouched.
        shutil.rmtree(runtime)


def wait_health(commit: str, source_hash: str) -> dict:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        try:
            return verify_health(request_json(8788, "/healthz"), commit, source_hash)
        except OperationFailure as exc:
            if exc.code in {"operation_deadline", "operation_interrupted"}:
                raise
            time.sleep(1)
        except (OSError, ValueError):
            time.sleep(1)
    raise OperationFailure("installed_health_failed")


def activate(candidate: Path, commit: str, source_hash: str, drain_proof: dict) -> dict:
    current = BASE / "current"
    if current.exists() and not current.is_symlink():
        raise OperationFailure("unrecognized_current_release")
    previous = str(current.resolve()) if current.is_symlink() else None
    previous_dropin = DROPIN.read_bytes() if DROPIN.exists() else None
    previous_health = request_json(8788, "/healthz")
    backup = {
        "targetCommit": commit,
        "previous": previous,
        "dropin": previous_dropin.decode() if previous_dropin else None,
    }
    atomic_bytes(candidate / "rollback.json", json.dumps(backup).encode())
    validate_drain_proof(drain_proof, commit, remaining=ACTIVATION_LEASE_REQUIRED + 250)
    wait_idle()
    # wait_idle itself may consume 240 seconds. Recheck at the last point before
    # the live unit can change, reserving both live inspections and rollback.
    validate_drain_proof(drain_proof, commit, remaining=ACTIVATION_LEASE_REQUIRED)
    try:
        with bounded_action(ACTIVATION_SECONDS):
            run(["systemctl", "stop", UNIT])
            atomic_link(candidate / "pi_host/dsh_ydmap", current)
            override = (
                MARKER + "[Service]\nExecStart=\n"
                f"ExecStart=/usr/bin/python3 {current}/server.py\n"
                f"Environment=YDMAP_DEPLOYMENT_COMMIT={commit}\n"
                "Environment=YDMAP_LISTEN_PORT=8788\nEnvironment=YDMAP_DEBUG_PORT=9224\n"
                "Environment=YDMAP_PROFILE=/tmp/dsh_ydmap_profile\n"
            )
            atomic_bytes(DROPIN, override.encode(), mode=0o644)
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "start", UNIT])
            report = wait_health(commit, source_hash)
            # The real systemd environment can differ from the isolated
            # candidate. Both real listener inspections are part of activation.
            inspections = inspect_venues(8788)
            report = verify_health(request_json(8788, "/healthz"), commit, source_hash)
            return {
                "applied": True,
                "health": report,
                "inspections": inspections,
                "liveInspectionsVerified": True,
                "rollbackAvailable": True,
            }
    except Exception as activation_error:
        restored = False
        try:
            with bounded_action(ROLLBACK_SECONDS, rollback=True):
                run(["systemctl", "stop", UNIT])
                if previous is not None:
                    atomic_link(Path(previous), current)
                else:
                    current.unlink(missing_ok=True)
                if previous_dropin is not None:
                    atomic_bytes(DROPIN, previous_dropin, mode=0o644)
                else:
                    DROPIN.unlink(missing_ok=True)
                run(["systemctl", "daemon-reload"])
                run(["systemctl", "start", UNIT])
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        restored_health = request_json(8788, "/healthz")
                        restored = restored_health.get("ok") is True and all(
                            restored_health.get(key) == previous_health.get(key)
                            for key in (
                                "service",
                                "protocolVersion",
                                "deploymentCommit",
                                "sourceSha256",
                            )
                        )
                        if restored:
                            break
                    except OperationFailure as exc:
                        if exc.code == "operation_deadline":
                            raise
                    except (OSError, ValueError):
                        pass
                    time.sleep(1)
        finally:
            failure = OperationFailure("activation_failed", rollback_verified=restored)
            if isinstance(activation_error, OperationFailure):
                failure.venue = activation_error.venue
                failure.inspections = activation_error.inspections
                failure.source_failure = activation_error.source_failure
                failure.source_diagnostic = activation_error.source_diagnostic
            raise failure from None


def operate(args) -> dict:
    before = other_service_identities()
    account = verify_existing_service()
    if args.operation == "apply":
        validate_drain_proof(args.drain_proof, args.commit)
    if args.operation in {"health", "inspect"}:
        health = verify_health(request_json(8788, "/healthz"), args.commit, args.source_sha256)
        evidence = inspect_venues(8788) if args.operation == "inspect" else []
        report = {"health": health, "inspections": evidence, "applied": False}
    else:
        candidate = prepare_candidate(args.staging, args.commit, args.source_sha256, account)
        with isolated_candidate(candidate, account, args.commit) as port:
            health = verify_health(request_json(port, "/healthz"), args.commit, args.source_sha256)
            evidence = (
                inspect_venues(port, source_evidence=True)
                if args.operation == "preflight"
                else inspect_venues(port)
            )
        if before != other_service_identities():
            raise OperationFailure("unrelated_service_changed")
        report = {
            "health": health,
            "inspections": evidence,
            "candidateVerified": True,
            "applied": False,
        }
        if args.operation == "apply":
            validate_drain_proof(args.drain_proof, args.commit)
            report.update(activate(candidate, args.commit, args.source_sha256, args.drain_proof))
    unchanged = before == other_service_identities()
    if not unchanged:
        raise OperationFailure("unrelated_service_changed")
    return {
        "ok": True,
        "operation": args.operation,
        "unrelatedServicesUnchanged": unchanged,
        "externalTestSends": 0,
        **report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preflight", "apply", "health", "inspect"))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--staging", type=Path)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise OperationFailure("operation_interrupted")

    for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, interrupted)
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit) or not re.fullmatch(
        r"[0-9a-f]{64}", args.source_sha256
    ):
        parser.error("invalid release identity")
    try:
        if os.geteuid() != 0:
            raise OperationFailure("root_required")
        if args.operation in {"preflight", "apply"} and not args.staging:
            raise OperationFailure("staging_required")
        args.drain_proof = json.load(sys.stdin) if args.operation == "apply" else None
        encoded = encode_report(
            {**operate(args), "operationComplete": True},
            source_evidence=args.operation == "preflight",
        )
        print(encoded)
        return 0 if json.loads(encoded).get("ok") is True else 1
    except Exception as exc:
        print(
            encode_report(
                {
                    "ok": False,
                    "operationComplete": True,
                    **failure_details(exc),
                    "failure": exc.code
                    if isinstance(exc, OperationFailure)
                    else "operation_failed",
                    "rollbackVerified": exc.rollback_verified
                    if isinstance(exc, OperationFailure)
                    else False,
                    "venue": exc.venue if isinstance(exc, OperationFailure) else None,
                    "inspections": exc.inspections if isinstance(exc, OperationFailure) else [],
                    "serviceDiagnostic": exc.service_diagnostic
                    if isinstance(exc, OperationFailure)
                    else None,
                    "sourceFailure": exc.source_failure
                    if isinstance(exc, OperationFailure)
                    else None,
                    "sourceDiagnostic": exc.source_diagnostic
                    if isinstance(exc, OperationFailure)
                    else {},
                    "externalTestSends": 0,
                },
                source_evidence=args.operation == "preflight",
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
