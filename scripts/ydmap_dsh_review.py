#!/usr/bin/env python3
"""Run the installed DSH's documented headless mode, without copying credentials."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ydmap_source_compare import redact

PROMPT = """用户授权你作为DSH协作智能体复核 wechat-on-airflow PR223。
请实际阅读当前独立工作目录内的公开代码，以静态分析和无网络的本地测试协查，不要只给泛泛计划。
问题：同属YDMap，大沙河正常，新场馆此前卡住。已确认：大沙河生产代码每轮也重建临时profile；其启动方式是先原生Chromium打开URL、等4秒再让Selenium连接。旧BAWTT脚本由ChromeDriver启动浏览器。
新的实际Pi对照run35068987410使用同一原生启动流程、各源独立profile，无UA或navigator覆写：大沙河出现8场号125时段单元，BAWTT室内111317和室外103224也出现ScheduleTable、产品及日期标签，但过早返回时cells/courts仍为空。三个来源均加载app.23918b62.js和booking-schedule-venue.b6226c5c.js。只能确定初始化路径有所推进，不能把空组件当成取数成功，也不能从一次组合配置改变直接证明某个单一参数就是根因。
补充最新对照：run35069607529改为about:blank启动、先附加Selenium及performance日志再driver.get导航时，连大沙河也停在AccessLoadingHolder，三个源的getConfig资源响应标为HTTP200/text-html；navigator.webdriver仍然false，不能单独据此归因该标志。先恢复原URL启动再延迟连接的成功顺序，避免观测工具改变初始化。
latest_observation.json是已完成运行日志的人工归一化事实摘要，含run/job/时间，可用作证据索引，不是新采集结果。最新run35070716599在大沙河发现自称可见的Slider组件后立即停止，BAWTT未访问。注意该检测只检查组件自身矩形/display/visibility，未检查祖先opacity/viewport等，不能直接把Slider组件存在当成确定的人机验证证据。请重点复核这个检测和后续等待数据的方式；不再访问站点。
请检查提供的ydmap_source_compare.py、bawtt_live_query.py、dashah_server.py与latest_observation.json，给出：1. 已有证据能/不能支持的原因；2. 查询捕获是否丢失早期请求或接受业务错误JSON；3. 下一步最小必要修复与回归测试；4. 同供应商也必须按来源验证的日期/可订状态规则。
重要边界：本任务只可读当前工作目录内三个公开代码文件和latest_observation.json，并可在本工作目录写无网络测试。不要访问网站、启动浏览器、读取系统/服务/其他DSH会话/认证/模型配置/.env/Cookie/密码/令牌，不修改生产、不重启、不安装依赖、不git push、不发通知、不下单。不要解决验证码或推荐绕过访问限制。不要读取此前受阻的任何DSH产物；它们与本任务无关。
输出最终一个JSON对象：{"result":"reviewed|partial","findings":["有依据的结论"],"minimal_fix":"具体建议","missing_evidence":["尚缺证据"]}。不要声称已完成上线或bookability验收，不要输出内部思考过程。
"""


def service_roots() -> tuple[list[Path], list[str]]:
    roots: list[Path] = []
    node_paths: list[str] = []
    for prop in ("WorkingDirectory", "ExecStart"):
        result = subprocess.run(
            ["systemctl", "show", "dsh-web.service", "--property=" + prop, "--value"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        if prop == "WorkingDirectory" and re.fullmatch(r"/[A-Za-z0-9_./-]{1,180}", result):
            roots.append(Path(result))
        if prop == "ExecStart":
            argv = re.search(r"argv\[\]=(.*?)(?: ; | ;}|$)", result)
            try:
                args = shlex.split(argv.group(1)) if argv else []
            except ValueError:
                args = []
            for entry in args[1:]:
                if (
                    re.fullmatch(r"/[A-Za-z0-9_@+./-]{1,220}", entry)
                    and Path(entry).suffix in (".js", ".mjs", ".cjs")
                    and (
                        re.search(r"dsh|deepseek", entry, re.I)
                        or entry.endswith("/apps/cli/lib/bin.js")
                    )
                ):
                    roots.extend(list(Path(entry).parents)[:3])
            for path in re.findall(r"(?:path=|argv\[\]=)(/[A-Za-z0-9_./-]+)", result):
                if Path(path).name in ("node", "nodejs"):
                    node_paths.append(path)
    node = shutil.which("node")
    if node:
        node_paths.append(node)
    for node_path in node_paths:
        prefix = Path(node_path).parent.parent
        roots.append(prefix / "lib/node_modules/@deepseek-ai/dsh")
    return list(dict.fromkeys(roots)), list(dict.fromkeys(node_paths))


def installed_command(report: dict[str, Any]) -> list[str] | None:
    binary = shutil.which("dsh")
    if binary:
        return [binary]
    roots, nodes = service_roots()
    report["serviceWorkingDirectoryFound"] = bool(roots)
    report["nodeAvailable"] = bool(nodes)
    report["candidateRootCount"] = len(roots)
    report["packageManifestNames"] = []
    checked: set[Path] = set()
    for root in roots:
        for package_root in (root, root / "apps/cli", root / "node_modules/@deepseek-ai/dsh"):
            manifest = package_root / "package.json"
            if manifest in checked:
                continue
            checked.add(manifest)
            if not manifest.is_file() or manifest.stat().st_size > 50000:
                continue
            value = json.loads(manifest.read_text())
            name = value.get("name")
            if isinstance(name, str) and re.fullmatch(r"[@A-Za-z0-9_./-]{1,80}", name):
                report["packageManifestNames"].append(name)
            if name != "@deepseek-ai/dsh":
                continue
            report["installedVersion"] = redact(value.get("version"))[:80]
            entry = value.get("bin", {})
            relative = entry.get("dsh") if isinstance(entry, dict) else entry
            if not isinstance(relative, str) or not re.fullmatch(
                r"[A-Za-z0-9_./-]{1,120}", relative
            ):
                continue
            target = (package_root / relative).resolve()
            if (
                not target.is_relative_to(package_root.resolve())
                or not target.is_file()
                or not nodes
            ):
                continue
            return [nodes[0], str(target)]
    return None


def main() -> None:
    report: dict[str, Any] = {
        "observedAt": datetime.now(UTC).isoformat(),
        "mode": "installed_dsh_headless_static_review",
        "invoked": False,
        "productionChanged": False,
        "externalTestSends": 0,
    }
    proc = None
    try:
        command = installed_command(report)
        if not command:
            report["state"] = "documented_cli_not_located"
            return
        help_result = subprocess.run(
            command + ["--help"], capture_output=True, text=True, timeout=20, check=False
        )
        if help_result.returncode or "--profile" not in help_result.stdout:
            report.update(
                state="installed_cli_contract_unconfirmed", helpExit=help_result.returncode
            )
            return
        with tempfile.TemporaryDirectory(prefix="ydmap-dsh-static-review-") as workspace:
            for name in (
                "ydmap_source_compare.py",
                "bawtt_live_query.py",
                "dashah_server.py",
                "latest_observation.json",
            ):
                Path(workspace, name).write_text(Path(__file__).with_name(name).read_text())
            env = os.environ.copy()
            env["DSH_PERMISSION_MODE"] = "workspace-write"
            env["DSH_TELEMETRY_DISABLED"] = "1"
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                proc = subprocess.Popen(
                    command + ["--profile", "headless", PROMPT],
                    cwd=workspace,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                report["invoked"] = True
                try:
                    exit_code = proc.wait(timeout=200)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                    report["state"] = "delegation_deadline_no_automatic_retry"
                    return
                stdout.seek(0)
                raw = stdout.read(65537)
                report["exitCode"] = exit_code
                report["finalText"] = (
                    redact(raw.decode(errors="replace")) if len(raw) <= 65536 else "[oversized]"
                )
                stderr.seek(0)
                errors = stderr.read(65536).decode(errors="replace")
                report["credentialSetupRequired"] = bool(
                    re.search(
                        r"missing.*(?:credential|api.?key)|api.?key.*(?:required|missing)|no.*credentials",
                        errors,
                        re.I,
                    )
                )
                report["state"] = (
                    "review_completed" if exit_code == 0 and raw.strip() else "cli_failed"
                )
    except Exception as error:
        report.update(state="delegation_failed", errorClass=type(error).__name__)
    finally:
        if proc and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
