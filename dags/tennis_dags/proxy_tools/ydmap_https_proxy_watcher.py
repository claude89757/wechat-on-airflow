#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024-03-20 02:35:46
@Author  : claude89757
@File    : ydmap_https_proxy_watcher.py
@Description : Airflow DAG for checking and updating HTTPS proxies
"""

# 标准库导入
import os
import random
import base64
from datetime import datetime, timedelta
import threading
import concurrent.futures

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable  # 需要保留这个导入，因为用于获取 GIT_TOKEN
import urllib3
import warnings

# 禁用所有与未验证HTTPS请求相关的警告
urllib3.disable_warnings()
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# 常量定义
LOCAL_FILENAME = "/tmp/isz_https_proxies.txt"
REMOTE_FILENAME = "https://api.github.com/repos/claude89757/free_https_proxies/contents/isz_https_proxies.txt"

def generate_proxies():
    """
    获取待检查的代理列表
    """
    urls = [
        "https://github.com/roosterkid/openproxylist/raw/main/HTTPS_RAW.txt",
        "https://raw.githubusercontent.com/yoannchb-pro/https-proxies/main/proxies.txt",
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
        "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt",
    ]
    proxies = []
    proxy_url_infos = {}
    
    print("开始获取代理列表...")
    for url in urls:
        try:
            response = requests.get(url)
            text = response.text.strip()
            lines = text.split("\n")
            lines = [line.strip() for line in lines if is_valid_proxy(line)]
            proxies.extend(lines)
            for line in lines:
                proxy_url_infos[line] = url
        except Exception as e:
            print(f"从 {url} 获取代理失败: {str(e)}")
            
    print(f"总计获取到 {len(proxies)} 个待检查代理")
    random.shuffle(proxies)
    return proxies, proxy_url_infos

def is_valid_proxy(proxy):
    # 简单的 IP 格式验证
    parts = proxy.split(':')
    if len(parts) != 2:
        return False
    ip, port = parts
    return ip.count('.') == 3 and port.isdigit()

def check_proxy(proxy_url, proxy_url_infos):
    """
    使用 requests 检查代理是否可用
    """
    try:
        target_url = 'https://wxsports.ydmap.cn/srv200/api/pub/basic/getConfig'
        
        proxies = {
            'http': f'http://{proxy_url}',
            'https': f'http://{proxy_url}'
        }
        
        response = requests.get(
            target_url,
            proxies=proxies,
            timeout=3,
            verify=False
        )
        
        response_text = response.text
        
        if response.status_code == 200 and "在线订场" in response_text:
            print(f"[{proxy_url}] 发现可用代理, 返回内容: {response_text}")
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{now}] 发现可用代理: {proxy_url}")
            return True
            
    except Exception:
        pass
    return False

def update_proxy_file(filename, available_proxies):
    """
    更新代理文件，保留最近的100个可用代理
    """
    # 先读取现有的代理
    try:
        with open(filename, "r") as file:
            existing_proxies = [line.strip() for line in file.readlines() if line.strip()]
    except FileNotFoundError:
        existing_proxies = []
    
    # 合并现有代理和新发现的代理，去除重复项
    all_proxies = []
    for proxy in available_proxies:
        if proxy not in all_proxies:
            all_proxies.append(proxy)
    
    for proxy in existing_proxies:
        if proxy not in all_proxies:
            all_proxies.append(proxy)
    
    # 如果超过100个，只保留最近的100个
    if len(all_proxies) > 100:
        all_proxies = all_proxies[:100]
    
    # 写入文件
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
    
    proxies, proxy_url_infos = generate_proxies()
    print(f"开始检查 {len(proxies)} 个代理...")
    
    available_proxies = []
    max_workers = 50  # 增加并发线程数，提高效率
    
    def check_and_process(proxy):
        if check_proxy(proxy, proxy_url_infos):
            with threading.Lock():  # 使用锁防止并发写入问题
                available_proxies.append(proxy)
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
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

def upload_file_to_github(filename):
    """
    将代理文件上传到GitHub
    """
    token = Variable.get('GIT_TOKEN')

    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    try:
        with open(filename, 'rb') as file:
            content = file.read()
            
        # 获取文件的SHA值
        sha = get_file_sha(REMOTE_FILENAME, headers)
        
        # 准备上传数据
        data = {
            'message': f'Update proxy list by airflow at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            'content': base64.b64encode(content).decode('utf-8')
        }
        
        # 如果SHA存在，添加到数据中
        if sha:
            data['sha'] = sha
            
        # 上传文件
        response = requests.put(REMOTE_FILENAME, headers=headers, json=data)
        
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
        # 检查本地文件是否存在
        if os.path.exists(LOCAL_FILENAME):
            print(f"本地文件 {LOCAL_FILENAME} 已存在，跳过下载")
            return
            
        # 从GitHub获取文件内容
        token = Variable.get('GIT_TOKEN')
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        response = requests.get(REMOTE_FILENAME, headers=headers)
        if response.status_code == 200:
            # 解码GitHub返回的base64内容
            try:
                file_content = base64.b64decode(response.json()['content']).decode('utf-8')
                
                # 检查内容是否是JSON格式（意外情况）
                if file_content.strip().startswith('{') and '"content":' in file_content:
                    print("警告: 文件内容似乎是一个JSON对象，尝试提取真正的代理列表")
                    try:
                        import json
                        data = json.loads(file_content)
                        if 'content' in data and isinstance(data['content'], str):
                            real_content = base64.b64decode(data['content']).decode('utf-8')
                            file_content = real_content
                    except Exception as json_err:
                        print(f"尝试解析JSON内容失败: {json_err}")
                
                # 确保每一行是有效的代理
                valid_proxies = []
                for line in file_content.split('\n'):
                    line = line.strip()
                    if is_valid_proxy(line):
                        valid_proxies.append(line)
                
                # 写入本地文件，每行一个代理
                with open(LOCAL_FILENAME, 'w') as file:
                    for proxy in valid_proxies:
                        file.write(proxy + '\n')
                
                print(f"文件已下载并保存到 {LOCAL_FILENAME}，包含 {len(valid_proxies)} 个有效代理")
            except Exception as decode_err:
                print(f"解码文件内容失败: {decode_err}")
                # 创建空文件
                with open(LOCAL_FILENAME, 'w') as file:
                    pass
        else:
            print(f"文件下载失败，创建空文件: {response.status_code}")
            # 创建空文件
            with open(LOCAL_FILENAME, 'w') as file:
                pass
    except Exception as e:
        print(f"下载文件时出错: {e}")
        # 确保文件存在
        with open(LOCAL_FILENAME, 'w') as file:
            pass

def get_file_sha(url, headers):
    """
    获取GitHub上文件的SHA，用于更新文件
    """
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()['sha']
    elif response.status_code == 404:
        print("文件在GitHub上不存在，将创建新文件")
        return None
    else:
        print(f"获取文件SHA失败: {response.status_code}, {response.text}")
        return None

# DAG的默认参数
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(minutes=60),
}

# 定义DAG
dag = DAG(
    dag_id='HTTPS可用代理巡检_ydmap',
    default_args=default_args,
    description='A DAG to check and update HTTPS proxies',
    schedule_interval='*/20 * * * *',
    start_date=datetime(2024, 1, 1),
    max_active_runs=1,
    catchup=False,
    tags=['proxy', 'ydmap'],
)

def run_proxy_checker():
    """Airflow任务的入口点"""
    task_check_proxies()

# 创建任务
check_proxies_task = PythonOperator(
    task_id='check_proxies',
    python_callable=run_proxy_checker,
    dag=dag,
)

# 设置任务依赖关系
check_proxies_task
