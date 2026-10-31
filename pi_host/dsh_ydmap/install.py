"""Bounded Pi scraper rollout; only the dedicated scrape service is changed."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
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
    if type(value.get("productInCatalog")) is bool:
        result["productInCatalog"] = value["productInCatalog"]
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


def inspect_evidence(payload: dict, venue: str, expected_dates: list[str]) -> dict:
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
    return {"venue": venue, "verified": True, "days": report_days}


def safe_inspections(value: object) -> list[dict]:
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
            safe = inspect_evidence(raw, report["venue"], [day["date"] for day in days])
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


def inspect_venues(port: int, *, at: datetime | None = None) -> list[dict]:
    reports = []
    local = at or datetime.now(ZoneInfo("Asia/Shanghai"))
    for venue, days, timeout in (("dsh", 5 if local.hour >= 12 else 4, 150), ("baoti", 2, 240)):
        today = local.date()
        expected = [(today + timedelta(days=offset)).isoformat() for offset in range(days)]
        try:
            payload = request_json(port, f"/inspect?venue={venue}&days={days}", timeout=timeout)
            reports.append(inspect_evidence(payload, venue, expected))
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
            "runuser",
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
    process = subprocess.Popen(
        [
            "runuser",
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
    try:
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
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
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
            evidence = inspect_venues(port)
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
        print(
            json.dumps(
                {**operate(args), "operationComplete": True}, ensure_ascii=False, sort_keys=True
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operationComplete": True,
                    "errorClass": type(exc).__name__,
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
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
