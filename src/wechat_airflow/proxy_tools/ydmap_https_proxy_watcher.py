#!/usr/bin/env python
"""
@Time    : 2024-03-20 02:35:46
@Author  : claude89757
@File    : ydmap_https_proxy_watcher.py
@Description : Check and update YDMap-compatible HTTPS proxies
"""

# 标准库导入
import base64
import concurrent.futures
import ipaddress
import random
import re
import threading
import warnings
from datetime import datetime

# 第三方库导入
import requests
import urllib3
from airflow.sdk import Variable

# 禁用所有与未验证HTTPS请求相关的警告
urllib3.disable_warnings()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# 常量定义
LOCAL_FILENAME = "/tmp/isz_https_proxies.txt"
REMOTE_FILENAME = (
    "https://api.github.com/repos/claude89757/free_https_proxies/contents/isz_https_proxies.txt"
)
BAOTI_TARGET_URL = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
SOURCE_TIMEOUT_SECONDS = 15
PROXY_CHECK_TIMEOUT_SECONDS = 5
GITHUB_TIMEOUT_SECONDS = 15
RATE_LIMIT_OR_CHALLENGE_RE = re.compile(
    r"(?:999998|频次过快|请求过于频繁|too\s+many\s+requests|rate\s+limit|"
    r"Access\s+Verification|slide\s+to\s+verify|访问\s*验证|安全\s*验证)",
    re.IGNORECASE,
)


def generate_proxies():
    """
    获取待检查的代理列表
    """
    urls = [
        "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/https_proxies.txt",
        "https://github.com/roosterkid/openproxylist/raw/main/HTTPS_RAW.txt",
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
        "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt",
    ]
    proxies = []
    seen = set()
    proxy_url_infos = {}

    print("开始获取代理列表...")
    for url in urls:
        try:
            response = requests.get(url, timeout=SOURCE_TIMEOUT_SECONDS)
            response.raise_for_status()
            text = response.text.strip()
            lines = text.split("\n")
            lines = [line.strip() for line in lines if is_valid_proxy(line.strip())]
            for line in lines:
                proxy_url_infos[line] = url
                if line not in seen:
                    seen.add(line)
                    proxies.append(line)
        except Exception as e:
            print(f"从 {url} 获取代理失败: {str(e)}")

    print(f"总计获取到 {len(proxies)} 个待检查代理")
    random.shuffle(proxies)
    return proxies, proxy_url_infos


def is_valid_proxy(proxy):
    # 校验全局 IPv4:port 格式
    if not isinstance(proxy, str):
        return False
    text = proxy.strip()
    if not text or any(ch.isspace() for ch in text) or "://" in text or "@" in text:
        return False
    parts = text.split(":")
    if len(parts) != 2:
        return False
    ip, port_text = parts
    if not port_text.isdigit():
        return False
    port = int(port_text)
    if not 1 <= port <= 65535:
        return False
    try:
        addr = ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        return False
    return bool(addr.is_global and not addr.is_multicast)


def check_proxy(proxy_url, proxy_url_infos):
    """
    使用 requests + 严格 TLS 检查代理是否可直接加载 bawtt.ydmap.cn 预约页面 HTML
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html",
        }
        proxies = {"http": f"http://{proxy_url}", "https": f"http://{proxy_url}"}
        response = requests.get(
            BAOTI_TARGET_URL,
            headers=headers,
            proxies=proxies,
            timeout=PROXY_CHECK_TIMEOUT_SECONDS,
            verify=True,
        )
        if response.status_code != 200:
            return False
        response_text = response.text
        if len(response_text) < 1000 or "<!doctype html>" not in response_text[:512].lower():
            return False
        if RATE_LIMIT_OR_CHALLENGE_RE.search(response_text[:4096]):
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] 发现可用代理: {proxy_url}")
        return True
    except Exception:
        pass
    return False


def update_proxy_file(filename, available_proxies):
    """
    更新代理文件：有新测活代理时仅保留本轮验活节点以剔除失效代理；
    若本轮 0 发现则保留最多 20 个旧节点作为安全兜底，避免瞬断清空列表。
    """
    try:
        with open(filename) as file:
            existing_proxies = [
                line.strip() for line in file.readlines() if is_valid_proxy(line.strip())
            ]
    except FileNotFoundError:
        existing_proxies = []

    all_proxies = []
    seen = set()
    for proxy in available_proxies:
        cleaned = proxy.strip() if isinstance(proxy, str) else ""
        if is_valid_proxy(cleaned) and cleaned not in seen:
            seen.add(cleaned)
            all_proxies.append(cleaned)
            if len(all_proxies) >= 100:
                break

    if not all_proxies:
        for proxy in existing_proxies:
            if proxy not in seen:
                seen.add(proxy)
                all_proxies.append(proxy)
                if len(all_proxies) >= 20:
                    break

    with open(filename, "w") as file:
        for proxy in all_proxies:
            file.write(proxy + "\n")

    print(f"代理文件已更新，共有 {len(all_proxies)} 个可用代理")


def task_check_proxies():
    """
    主要检查代理的任务函数，使用并发提高效率
    """
    print("开始代理检查任务...")
    download_file()

    try:
        with open(LOCAL_FILENAME) as file:
            existing_proxies = [
                line.strip() for line in file.readlines() if is_valid_proxy(line.strip())
            ]
    except FileNotFoundError:
        existing_proxies = []

    fetched_proxies, proxy_url_infos = generate_proxies()
    proxies = []
    seen = set()
    for proxy in existing_proxies + fetched_proxies:
        if proxy not in seen:
            seen.add(proxy)
            proxies.append(proxy)
            proxy_url_infos.setdefault(proxy, LOCAL_FILENAME)
    print(f"开始检查 {len(proxies)} 个代理（含现有 {len(existing_proxies)} 个复检）...")

    available_proxies = []
    max_workers = 50
    lock = threading.Lock()

    def check_and_process(proxy):
        if check_proxy(proxy, proxy_url_infos):
            with lock:
                available_proxies.append(proxy)
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{now}] 当前可用代理数量: {len(available_proxies)}")

    # 使用线程池并发检查代理
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 使用列表推导式提交所有任务并获取future对象
        futures = [executor.submit(check_and_process, proxy) for proxy in proxies]

        # 使用as_completed可以在代理检查完成后立即处理结果
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()  # 获取结果，如果有异常会抛出
            except Exception as e:
                print(f"代理检查过程中出现异常: {e}")

    print(f"检查完成，共发现 {len(available_proxies)} 个可用代理")

    # 更新代理文件并上传到GitHub
    update_proxy_file(LOCAL_FILENAME, available_proxies)
    upload_file_to_github(LOCAL_FILENAME)

    # 更新到airflow的变量中
    isz_successful_proxies = Variable.get(
        "ISZ_SUCCESSFUL_PROXIES", deserialize_json=True, default=[]
    )
    for proxy in available_proxies:
        if proxy not in isz_successful_proxies:
            isz_successful_proxies.append(
                {
                    "https": f"http://{proxy}",
                }
            )
    # Variable.set('ISZ_SUCCESSFUL_PROXIES', isz_successful_proxies, serialize_json=True,
    #              description=f"update by ydmap_https_proxy_watcher at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    Variable.delete("ISZ_SUCCESSFUL_PROXIES")


def upload_file_to_github(filename):
    """
    将代理文件上传到GitHub
    """
    token = Variable.get("GIT_TOKEN")

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    try:
        with open(filename, "rb") as file:
            content = file.read()

        # 获取文件的SHA值
        sha = get_file_sha(REMOTE_FILENAME, headers)

        # 准备上传数据
        data = {
            "message": f"Update proxy list by airflow at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": base64.b64encode(content).decode("utf-8"),
        }

        # 如果SHA存在，添加到数据中
        if sha:
            data["sha"] = sha

        # 上传文件
        response = requests.put(
            REMOTE_FILENAME,
            headers=headers,
            json=data,
            timeout=GITHUB_TIMEOUT_SECONDS,
        )

        if response.status_code in (200, 201):
            print("代理文件成功上传到GitHub")
        else:
            print(f"上传文件失败: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"上传文件时出错: {e}")


def download_file():
    """
    从GitHub下载代理文件，确保不覆盖现有代理
    """
    try:
        # 从GitHub获取文件内容
        token = Variable.get("GIT_TOKEN")
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

        response = requests.get(
            REMOTE_FILENAME,
            headers=headers,
            timeout=GITHUB_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            # 解码GitHub返回的base64内容
            try:
                file_content = base64.b64decode(response.json()["content"]).decode("utf-8")

                # 检查内容是否是JSON格式（意外情况）
                if file_content.strip().startswith("{") and '"content":' in file_content:
                    print("警告: 文件内容似乎是一个JSON对象，尝试提取真正的代理列表")
                    try:
                        import json

                        data = json.loads(file_content)
                        if "content" in data and isinstance(data["content"], str):
                            real_content = base64.b64decode(data["content"]).decode("utf-8")
                            file_content = real_content
                    except Exception as json_err:
                        print(f"尝试解析JSON内容失败: {json_err}")

                # 确保每一行是有效的代理
                valid_proxies = []
                for line in file_content.split("\n"):
                    line = line.strip()
                    if is_valid_proxy(line):
                        valid_proxies.append(line)

                # 写入本地文件，每行一个代理
                with open(LOCAL_FILENAME, "w") as file:
                    for proxy in valid_proxies:
                        file.write(proxy + "\n")

                print(f"文件已下载并保存到 {LOCAL_FILENAME}，包含 {len(valid_proxies)} 个有效代理")
            except Exception as decode_err:
                print(f"解码文件内容失败: {decode_err}")
                # 创建空文件
                with open(LOCAL_FILENAME, "w") as file:
                    pass
        else:
            print(f"文件下载失败，创建空文件: {response.status_code}")
            # 创建空文件
            with open(LOCAL_FILENAME, "w") as file:
                pass
    except Exception as e:
        print(f"下载文件时出错: {e}")
        # 确保文件存在
        with open(LOCAL_FILENAME, "w") as file:
            pass


def get_file_sha(url, headers):
    """
    获取GitHub上文件的SHA，用于更新文件
    """
    response = requests.get(url, headers=headers, timeout=GITHUB_TIMEOUT_SECONDS)
    if response.status_code == 200:
        return response.json()["sha"]
    elif response.status_code == 404:
        print("文件在GitHub上不存在，将创建新文件")
        return None
    else:
        print(f"获取文件SHA失败: {response.status_code}, {response.text}")
        return None
