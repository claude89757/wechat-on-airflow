#!/usr/bin/env python3
"""Bounded Pi-local collaboration; no authentication material leaves this host."""
from __future__ import annotations

import fcntl
import http.cookiejar
import importlib.util
import json
import os
import re
import stat
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path.home() / ".local/state/wechat-on-airflow/dsh-assist"
ORIGINS = ("http://127.0.0.1:3080", "http://localhost:3080")
MISSION = "bawtt-104036-query-20260916"
PROMPT = """你是树莓派上协作的 DeepSeek Harness 智能体。用户已授权你协助排查 wechat-on-airflow 的网球场只读查询接入。主智能体负责后续代码审查、测试和 PR223 整合；你不要合并或部署。
目标只限两处公开预订查询入口：
室内 https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317
室外 https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=103224
GitHub runner 访问两个 URL 均是200但正文170字符、无script、无#app；这不是无空场证据。你现在就在真实树莓派上，请立即执行实际只读探测，而不是仅提出计划。
请使用已有 Python/Chromium/Selenium 能力，先看普通HTTP响应是否真正是应用页面，再用隔离临时浏览器profile访问。不得使用/删除/杀死现有生产 profile /tmp/dsh_ydmap_profile 或调试端口9224，不能重启任何服务，不能更改DSH或系统配置，不安装系统依赖。可以在本任务工作目录写诊断脚本/临时文件。并发已有浏览器时应保护现有巡检。
请在正常公开查询权限内检查页面实际请求的Network/XHR接口及公开JS资源，核实场馆名称、室内/室外产品ID、日期、场号和可订状态字段。不要假设Vue ScheduleTable一定存在；不要把加载占位/未放场/disabled/旧日期当空场。遇到验证码或需要登录的访问检查应停止该路径并报告，不绕过或读取别人会话。
参考实现可公开读取 GitHub仓库 claude89757/wechat-on-airflow 的 pi_host/dsh_ydmap/server.py；大沙河URL和第五天12点规则是场馆特例，不能照搬。只读本机 http://127.0.0.1:8788/healthz 已验证JSON ok=true，不必再次排查其他隧道。
严格边界：不要发送微信/邮件，不要下单锁场或付款，不要访问订阅数据库，不读任何.env、SSH密钥、DSH认证/模型配置、浏览器Cookie或令牌，不输出凭证、账号、住址、订阅者信息。不读取其他DSH会话。只对本任务工作目录写文件，不改生产文件，不git push、不sudo、不扩大权限。
在约4分钟的研究范围内交付能验证的内容，失败同样记录确切证据。最终回答只用一个JSON对象，无markdown：
{"result":"verified|partial|blocked","root_cause":"有证据的原因，未知就说明","recommended_fix":"具体接入方式",
"indoor":{"http_status":0,"page_loaded":false,"venue_name":"","court_count":0,"dates":[],"bookability_verified":false,"api_paths":[],"error":""},
"outdoor":{"http_status":0,"page_loaded":false,"venue_name":"","court_count":0,"dates":[],"bookability_verified":false,"api_paths":[],"error":""},
"artifact_files":["本工作目录内相对脚本名"]}
没有测到的字段用null或false，不能编造成功。api_paths仅路径，不含query/token/host。返回前清理自己启动的浏览器，但保留工作目录内的诊断脚本。"""


class Fault(RuntimeError):
    pass


def private_read(path: Path) -> dict[str, Any]:
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077 or meta.st_uid != os.getuid():
        raise Fault("unsafe_private_file")
    result = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise Fault("invalid_private_state")
    return result


def save(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, origin: str, cookies: dict[str, str] | None = None) -> None:
        if origin not in ORIGINS:
            raise Fault("invalid_origin")
        self.origin, self.cookies = origin, cookies or {}
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self.jar), NoRedirect()
        )

    def request(self, url: str, payload: object = None) -> tuple[int, bytes]:
        req = urllib.request.Request(
            url, data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Cookie": "; ".join(k + "=" + v for k, v in self.cookies.items())},
        )
        try:
            response = self.opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise Fault("oversized_response")
            return response.status, raw

    def rpc(self, method: str, request: object = None, *, args: object = None) -> Any:
        status, raw = self.request(self.origin + "/api/" + method, {
            "type": "client-request", "rpcId": uuid.uuid4().hex, "method": method,
            "payload": {"args": args if args is not None else {"request": request}},
        })
        if status != 200:
            raise Fault("rpc_http_" + str(status))
        result = json.loads(raw)["result"]
        if result.get("ok") is not True:
            raise Fault("rpc_rejected_" + method.replace("/", "_"))
        return result.get("value")

    def socket(self):
        import websocket
        return websocket.create_connection(
            self.origin.replace("http:", "ws:") + "/api/remote.mux",
            cookie="; ".join(k + "=" + v for k, v in self.cookies.items()),
            origin=self.origin, timeout=15, http_no_proxy=["127.0.0.1", "localhost"],
        )


def authenticate(report: dict[str, Any]) -> Client:
    path = ROOT / "auth.json"
    if path.exists():
        data = private_read(path)
        client = Client(data["url"], data["cookies"])
        client.rpc("session/modelCatalog", args={})
        report["loginMethod"] = "existing_owner_cookie"
        return client
    proc = subprocess.run(
        ["systemctl", "show", "dsh-web.service", "--property=MainPID", "--value"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    pid = proc.stdout.strip()
    if not pid.isdigit() or int(pid) <= 1:
        raise Fault("dsh_service_not_active")
    texts: list[str] = []
    # Follow only the running service's ordinary stdout/stderr log destinations.
    # No credential files, environment dumps, signing keys, or browser cookies.
    for fd in ("1", "2"):
        try:
            log = Path(os.readlink("/proc/" + pid + "/fd/" + fd))
            if not log.is_absolute() or not log.is_file() or log.is_symlink():
                continue
            if not (str(log).startswith("/var/log/") or log.is_relative_to(Path.home()) or str(log).startswith("/tmp/")):
                continue
            with log.open("rb") as handle:
                raw = handle.read(1024 * 1024)
                if log.stat().st_size > 1024 * 1024:
                    handle.seek(max(0, log.stat().st_size - 262144))
                    raw += handle.read(262144)
            texts.append(raw.decode(errors="replace"))
        except OSError:
            continue
    report["stdoutLogsRead"] = len(texts)
    launches = re.findall(r"http://(?:127\.0\.0\.1|localhost):3080/\?token=[A-Za-z0-9._~%-]+", "\n".join(texts))
    if not launches:
        raise Fault("normal_launch_link_required")
    launch = launches[-1]
    client = Client(launch.split("/?token=", 1)[0])
    status, _ = client.request(launch)
    if status != 303 or not list(client.jar):
        raise Fault("normal_login_rejected")
    client.cookies = {cookie.name: cookie.value for cookie in client.jar}
    client.rpc("session/modelCatalog", args={})
    save(path, {"url": client.origin, "cookies": client.cookies})
    report["loginMethod"] = "normal_service_launch_link"
    return client


def open_stream(ws, method: str, request: object = None, *, args: object = None) -> str:
    stream_id = uuid.uuid4().hex
    ws.send(json.dumps({"type": "open", "streamId": stream_id, "endpoint": method,
                        "payload": {"args": args if args is not None else {"request": request}}}))
    return stream_id


def snapshot(client: Client, sid: str) -> dict[str, Any]:
    ws = client.socket()
    try:
        stream_id = open_stream(ws, "session/follow", {"address": {"kind": "session", "sessionId": sid}, "maxMessages": 100})
        while True:
            frame = json.loads(ws.recv())
            if frame.get("type") in ("error", "end"):
                raise Fault("snapshot_stream_rejected")
            if frame.get("streamId") != stream_id:
                continue
            value = frame["value"]
            if value.get("type") != "snapshot" or value.get("header", {}).get("id") != sid:
                raise Fault("snapshot_identity_mismatch")
            return value
    finally:
        ws.close()


def clean_text(value: object, max_length: int = 1600) -> str:
    text = str(value or "")[:max_length]
    text = re.sub(r"https?://[^\s]+", "[URL omitted]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email omitted]", text)
    text = re.sub(r"(?i)(token|password|authorization|cookie|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=[omitted]", text)
    text = re.sub(r"(?<!\w)[A-Za-z0-9_=-]{48,}(?!\w)", "[opaque value omitted]", text)
    return text


def result_summary(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        value = json.loads(stripped)
    except ValueError:
        return {"structured": False, "summary": clean_text(text)}
    if not isinstance(value, dict):
        return {"structured": False}
    result: dict[str, Any] = {"structured": True}
    result["result"] = value.get("result") if value.get("result") in ("verified", "partial", "blocked") else "unknown"
    for key in ("root_cause", "recommended_fix"):
        result[key] = clean_text(value.get(key))
    for kind in ("indoor", "outdoor"):
        raw = value.get(kind)
        if not isinstance(raw, dict):
            continue
        target: dict[str, Any] = {}
        for key in ("http_status", "court_count", "page_loaded", "bookability_verified"):
            target[key] = raw.get(key) if type(raw.get(key)) in (int, bool) else None
        for key in ("venue_name", "error"):
            target[key] = clean_text(raw.get(key), 400)
        target["dates"] = [d for d in raw.get("dates", []) if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)][:14]
        target["api_paths"] = [p for p in raw.get("api_paths", []) if isinstance(p, str) and re.fullmatch(r"/[A-Za-z0-9_./-]{1,150}", p)][:20]
        result[kind] = target
    result["artifact_files"] = [p for p in value.get("artifact_files", []) if isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9_./-]{1,120}", p) and not p.startswith("/") and ".." not in p][:20]
    return result


def fold(job: dict[str, Any], event: dict[str, Any]) -> None:
    if event["seq"] <= job["seen"]:
        return
    if event["seq"] != job["seen"] + 1:
        raise Fault("event_sequence_gap")
    job["seen"] = event["seq"]
    kind, data = event["type"], event["data"]
    if kind == "turn/start":
        job["active_turn"] = data["turn"]
    if kind == "user/message":
        source = data.get("source", {})
        if source.get("rpcId") == job["request_id"]:
            job["turn"] = job.get("active_turn")
            job["status"] = "running"
        elif source.get("kind") == "user":
            job["foreign_activity"] = True
            raise Fault("foreign_session_activity")
    if not job.get("turn") or data.get("turn") != job["turn"]:
        return
    if kind == "tool/call":
        job["tool_calls"] = job.get("tool_calls", 0) + 1
    if kind == "assistant/message":
        message = data.get("message", {})
        source = message.get("source", {})
        if source.get("kind") == "model":
            job["actual_model"] = {k: source.get(k) for k in ("provider", "model")}
            expected = job.get("default_model", {})
            if any(expected.get(k) and expected[k] != source.get(k) for k in ("provider", "model")):
                job["model_mismatch"] = True
        text = "".join(b.get("text", "") for b in message.get("content", []) if b.get("type") == "text")
        if text:
            job["last_message"] = text
    if kind == "turn/end":
        job["end_kind"] = data.get("reason", {}).get("kind")
        job["status"] = "completed" if job["end_kind"] == "completed" and job.get("actual_model") and job.get("last_message") and not job.get("model_mismatch") else "failed"


def run() -> dict[str, Any]:
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise Fault("unsafe_state_directory")
    report: dict[str, Any] = {"productionRuntimeChanged": False, "externalTestSends": 0, "delegationSubmitted": False}
    try:
        client = authenticate(report)
    except Exception as exc:
        report.update(authenticated=False, status="auth_required", errorClass=type(exc).__name__)
        if isinstance(exc, Fault):
            report["reason"] = str(exc)
        return report
    report["authenticated"] = True
    if importlib.util.find_spec("websocket") is None:
        raise Fault("websocket_client_missing")
    receipt = ROOT / (MISSION + ".json")
    lock_fd = os.open(ROOT / (MISSION + ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    ws = None
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if receipt.exists():
            old = private_read(receipt)
            report.update({k: old.get(k) for k in ("session_id", "request_id", "status", "tool_calls", "actual_model")})
            report["reason"] = "existing_receipt_not_resubmitted"
            report["delegationSubmitted"] = old.get("submitted", False)
            if old.get("last_message"):
                report["agentReport"] = result_summary(old["last_message"])
            return report
        workspace = ROOT / "workspaces" / MISSION
        workspace.mkdir(parents=True, mode=0o700, exist_ok=False)
        job = {"session_id": "dsh-" + uuid.uuid4().hex[:16], "request_id": uuid.uuid4().hex,
               "workspace": str(workspace), "status": "preparing", "submitted": False, "tool_calls": 0}
        save(receipt, job)
        sid = job["session_id"]
        catalog = client.rpc("session/modelCatalog", args={})
        job["default_model"] = catalog.get("default", {})
        created = client.rpc("workspace/create", {"path": str(workspace)})["workspace"]
        if Path(created["path"]).resolve() != workspace.resolve():
            raise Fault("workspace_mismatch")
        client.rpc("session/create", {"sessionId": sid, "workspaceId": created["workspaceId"]})
        client.rpc("session/rename", {"sessionId": sid, "title": "BAWTT 104036 室内/室外只读诊断 · PR223"})
        client.rpc("commands/execute", args={"agentId": sid, "line": "/permission workspace-write", "submittedAttachments": []})
        snap = snapshot(client, sid)
        if Path(snap["header"]["cwd"]).resolve() != workspace.resolve():
            raise Fault("session_workspace_mismatch")
        if snap["projections"]["values"]["permissions"]["currentValue"] != "workspace-write":
            raise Fault("permission_mismatch")
        job.update(baseline=snap["cursor"], seen=snap["cursor"], status="prepared")
        save(receipt, job)
        ws = client.socket()
        events_id = open_stream(ws, "$events", args={})
        follow_id = open_stream(ws, "session/follow", {"address": {"kind": "session", "sessionId": sid}, "maxMessages": 100})
        ready = following = False
        until = time.monotonic() + 280
        ws.settimeout(2)
        import websocket
        while time.monotonic() < until:
            try:
                frame = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if frame.get("type") in ("error", "end"):
                raise Fault("stream_closed")
            value = frame.get("value", {})
            if frame.get("streamId") == events_id:
                if value.get("type") == "ready":
                    ready = True
                    client_id = value["clientId"]
                if value.get("type") == "waterfall":
                    if value.get("agentId") == sid:
                        job["approval_needed"] = value.get("event")
                        job["status"] = "needs_input"
                        save(receipt, job)
                        break
                    client.rpc("$events/result", args={"clientId": client_id, "eventId": value["eventId"], "outcome": {"kind": "next"}})
            if frame.get("streamId") == follow_id:
                if value.get("type") == "snapshot":
                    if value["header"]["id"] != sid or value.get("hasMore"):
                        raise Fault("unexpected_session_snapshot")
                    for event in sorted((r["event"] for r in value["records"] if r.get("type") == "event"), key=lambda e: e["seq"]):
                        fold(job, event)
                    following = True
                elif value.get("type") == "event":
                    fold(job, value["event"])
            if ready and following and job["status"] == "prepared":
                job["status"] = "sending"
                save(receipt, job)
                client.rpc("session/prompt", {"sessionId": sid, "requestId": job["request_id"], "mode": "queue", "content": [{"type": "text", "text": PROMPT}]})
                job.update(submitted=True, status="queued")
            save(receipt, job)
            if job["status"] in ("completed", "failed"):
                break
        if job["status"] not in ("completed", "failed"):
            client.rpc("session/cancel", {"sessionId": sid})
            job["status"] = "cancellation_requested"
            save(receipt, job)
        report.update({k: job.get(k) for k in ("session_id", "request_id", "status", "tool_calls", "actual_model", "approval_needed")})
        report["delegationSubmitted"] = job["submitted"]
        if job.get("last_message"):
            report["agentReport"] = result_summary(job["last_message"])
        return report
    except Exception as exc:
        if "job" in locals():
            job["error_class"] = type(exc).__name__
            if isinstance(exc, Fault):
                job["error_code"] = str(exc)
            job["status"] = "unknown" if job.get("submitted") or job.get("status") == "sending" else "failed_before_prompt"
            save(receipt, job)
            report.update({k: job.get(k) for k in ("session_id", "request_id", "status", "error_class", "error_code")})
            report["delegationSubmitted"] = job.get("submitted", False)
            return report
        raise
    finally:
        if ws is not None:
            ws.close()
        os.close(lock_fd)


if __name__ == "__main__":
    try:
        outcome = run()
    except Exception as exc:
        # No raw transport exceptions, headers, service log text, or secret fields.
        outcome = {"status": "failed_or_unknown", "errorClass": type(exc).__name__}
        if isinstance(exc, Fault):
            outcome["reason"] = str(exc)
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True), flush=True)
