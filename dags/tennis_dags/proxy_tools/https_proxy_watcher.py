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
from datetime import datetime, timedelta

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

def check_proxy(candidate_proxy, proxy_url_infos):
    """检查代理是否可用"""
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
    latest_proxies = all_proxies[:50]

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
    """主任务函数"""
    download_file()
    proxies, proxy_url_infos = generate_proxies()
    print(f"start checking {len(proxies)} proxies")
    
    available_proxies = []
    for proxy in proxies:
        if check_proxy(proxy, proxy_url_infos):
            available_proxies.append(proxy)
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"{now} Available proxies: {len(available_proxies)}")
            
            if len(available_proxies) >= 10:
                # 当收集到足够的代理时才更新文件
                update_proxy_file(LOCAL_FILENAME, available_proxies)
                upload_file_to_github(LOCAL_FILENAME)
                break
    
    if not available_proxies:
        print("No available proxies found, keeping existing ones")
    
    print("check end.")

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
    schedule_interval='*/30 * * * *',
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
