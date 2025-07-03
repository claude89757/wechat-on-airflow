#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024-03-20 02:35:46
@Author  : claude89757
@File    : https_proxy_watcher.py
@Description : Airflow DAG for checking and updating HTTPS proxies (Sync version)
"""

# 标准库导入
import os
import random
import base64
import concurrent.futures
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable


# 常量定义
LOCAL_FILENAME = "/tmp/https_proxies.txt"
REMOTE_FILENAME = "https://api.github.com/repos/claude89757/free_https_proxies/contents/https_proxies.txt"


def generate_proxies():
    """获取待检查的代理列表"""
    urls = [
        "https://github.com/roosterkid/openproxylist/raw/main/HTTPS_RAW.txt",
        "https://raw.githubusercontent.com/yoannchb-pro/https-proxies/main/proxies.txt",
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
        "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt",
    ]
    candidate_proxies = []
    proxy_url_infos = {}

    for url in urls:
        print(f"getting proxy list for {url}")
        response = requests.get(url)
        text = response.text.strip()
        lines = text.split("\n")
        lines = [line.strip() for line in lines if is_valid_proxy(line)]
        candidate_proxies.extend(lines)
        print(f"Loaded {len(lines)} proxies from {url}")
        for line in lines:
            proxy_url_infos[line] = url
    
    print(f"Total {len(candidate_proxies)} proxies loaded")
    random.shuffle(candidate_proxies)
    return candidate_proxies, proxy_url_infos

def is_valid_proxy(proxy):
    # 简单的 IP 格式验证
    parts = proxy.split(':')
    if len(parts) != 2:
        return False
    ip, port = parts
    return ip.count('.') == 3 and port.isdigit()

def check_proxy_with_info(proxy, proxy_url_infos):
    """检查代理是否可用，返回详细信息"""
    try:
        # 检查代理时不使用系统代理
        response = requests.get("https://www.baidu.com/", proxies={"https": proxy}, timeout=3)
        if response.status_code == 200:
            return {
                'proxy': proxy,
                'status': 'success',
                'source': proxy_url_infos.get(proxy)
            }
    except Exception:
        pass
    return {
        'proxy': proxy,
        'status': 'failed',
        'source': proxy_url_infos.get(proxy)
    }

def check_proxy(candidate_proxy, proxy_url_infos):
    """检查代理是否可用（保留原函数以兼容）"""
    try:
        # 检查代理时不使用系统代理
        response = requests.get("https://www.baidu.com/", proxies={"https": candidate_proxy}, timeout=3)
        if response.status_code == 200:
            print(f"[OK]  {candidate_proxy}, from {proxy_url_infos.get(candidate_proxy)}")
            return candidate_proxy
    except:
        pass
    return None

def update_proxy_file(filename, available_proxies):
    """更新代理文件，保留最新的100个代理
    
    Args:
        filename: 代理文件路径
        available_proxies: 新的可用代理列表
    """
    try:
        # 读取现有代理
        with open(filename, "r") as file:
            existing_proxies = [line.strip() for line in file.readlines()]
    except FileNotFoundError:
        existing_proxies = []

    # 合并现有代理和新代理，去重
    all_proxies = []
    # 首先添加新的可用代理
    for proxy in available_proxies:
        if proxy not in all_proxies:
            all_proxies.append(proxy)
    # 然后添加现有代理
    for proxy in existing_proxies:
        if proxy not in all_proxies:
            all_proxies.append(proxy)

    # 只保留最新的100个代理
    latest_proxies = all_proxies[:100]

    # 写入文件
    with open(filename, "w") as file:
        for proxy in latest_proxies:
            file.write(proxy + "\n")

def upload_file_to_github(filename):
    token = Variable.get('GIT_TOKEN')
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    with open(LOCAL_FILENAME, 'rb') as file:
        content = file.read()
    data = {
        'message': 'Update proxy list by airflow',
        'content': base64.b64encode(content).decode('utf-8'),
        'sha': get_file_sha(REMOTE_FILENAME, headers)
    }
    response = requests.put(REMOTE_FILENAME, headers=headers, json=data)
    if response.status_code == 200:
        print("File uploaded successfully.")
    else:
        print("Failed to upload file:", response.status_code, response.text)

def download_file():
    try:
        response = requests.get(REMOTE_FILENAME)
        response.raise_for_status()
        
        # GitHub API 返回的是 JSON 格式，包含 base64 编码的内容
        content = response.json().get('content', '')
        if content:
            decoded_content = base64.b64decode(content).decode('utf-8')
            # 计算当前代理数量
            current_proxies = [line.strip() for line in decoded_content.split('\n') if line.strip()]
            print(f"Current proxies count: {len(current_proxies)}")
            
            with open(LOCAL_FILENAME, 'w') as file:
                file.write(decoded_content)
            print(f"File downloaded and saved to {LOCAL_FILENAME}")
        else:
            print("No content found in the response")
    except requests.RequestException as e:
        print(f"Failed to download the file: {e}")
        # 如果下载失败，确保创建一个空文件
        with open(LOCAL_FILENAME, 'w') as file:
            pass

def get_file_sha(url, headers):
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()['sha']
    return None

def task_check_proxies():
    """主任务函数 - 使用并发检查代理"""
    download_file()
    proxies, proxy_url_infos = generate_proxies()
    print(f"开始并发检查 {len(proxies)} 个代理")
    
    available_proxies = []
    max_workers = 50  # 并发线程数，避免过高对目标网站造成压力
    target_proxy_count = 20  # 目标代理数量
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_proxy = {
            executor.submit(check_proxy_with_info, proxy, proxy_url_infos): proxy 
            for proxy in proxies
        }
        
        print(f"已提交 {len(future_to_proxy)} 个并发检查任务，最大并发数: {max_workers}")
        
        try:
            for future in as_completed(future_to_proxy):
                result = future.result()
                if result['status'] == 'success':
                    available_proxies.append(result['proxy'])
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(f"{now} [OK] {result['proxy']}, 来源: {result['source']}")
                    print(f"{now} 已找到可用代理: {len(available_proxies)}/{target_proxy_count}")
                    
                    if len(available_proxies) >= target_proxy_count:
                        print(f"已收集到足够的代理 ({len(available_proxies)}个)，停止检查")
                        # 取消剩余未完成的任务
                        for f in future_to_proxy:
                            if not f.done():
                                f.cancel()
                        break
                        
        except KeyboardInterrupt:
            print("检查被中断，正在取消剩余任务...")
            for f in future_to_proxy:
                f.cancel()
    
    if available_proxies:
        print(f"更新代理文件，共 {len(available_proxies)} 个可用代理")
        update_proxy_file(LOCAL_FILENAME, available_proxies)
        upload_file_to_github(LOCAL_FILENAME)
    else:
        print("未找到可用代理，保持现有代理")
    
    print("代理检查完成")

# DAG配置
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(minutes=30),
}

# 定义DAG
dag = DAG(
    dag_id='HTTPS可用代理巡检',
    default_args=default_args,
    description='A DAG to check and update HTTPS proxies (Sync version)',
    schedule_interval='*/5 * * * *',
    start_date=datetime(2024, 1, 1),
    dagrun_timeout=timedelta(minutes=30),
    max_active_runs=1,
    catchup=False,
    tags=['proxy'],
)

# 创建任务
check_proxies_task = PythonOperator(
    task_id='check_proxies',
    python_callable=task_check_proxies,
    dag=dag,
)

# 设置任务依赖关系
check_proxies_task
