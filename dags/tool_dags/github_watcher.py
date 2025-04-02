#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub仓库巡检DAG

功能：
1. 每5分钟查询一次GitHub仓库的提交记录
2. 如果有新的提交记录，将其缓存到最近的提交记录列表中
3. 使用Redis存储提交记录列表
"""

# 标准库导入
from datetime import datetime, timedelta
import json
import os

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from redis import Redis

GITHUB_OWNER = "claude89757"
GITHUB_REPO = "wechat-on-airflow"

# DAG ID
DAG_ID = f"{GITHUB_OWNER}_{GITHUB_REPO}_watcher"

# Redis键名称
REDIS_KEY = f"{GITHUB_OWNER}_{GITHUB_REPO}_recent_commits"

# 最大保存的提交记录数量
MAX_COMMITS = 20

def get_latest_commits(**context):
    """
    从GitHub获取最新的提交记录
    
    Args:
        **context: Airflow上下文参数
    
    Returns:
        None
    """
    github_token = Variable.get("GITHUB_TOKEN", default_var="")
    
    # 构建API URL
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits"
    
    # 设置请求头
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 如果有token则添加认证信息
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        # 请求GitHub API
        response = requests.get(api_url, headers=headers, params={"per_page": 10})
        response.raise_for_status()
        
        # 解析响应
        commits = response.json()
        
        if not commits or not isinstance(commits, list):
            print(f"未获取到有效的提交记录")
            return
        
        # 连接Redis
        redis_client = Redis(host='airflow_redis', port=6379, decode_responses=True)
        
        # 获取现有的提交记录
        existing_commits_json = redis_client.get(REDIS_KEY)
        existing_commits = json.loads(existing_commits_json) if existing_commits_json else []
        
        # 检查是否有新提交
        latest_commit_sha = commits[0]["sha"]
        
        # 如果没有现有提交或者最新提交与缓存中的不同，则更新缓存
        has_new_commits = False
        if not existing_commits or latest_commit_sha != existing_commits[0]["sha"]:
            has_new_commits = True
            print(f"发现新的提交记录，SHA: {latest_commit_sha}")
            
            # 提取需要保存的提交信息
            new_commits = []
            for commit in commits:
                commit_info = {
                    "sha": commit["sha"],
                    "message": commit["commit"]["message"],
                    "author": commit["commit"]["author"]["name"],
                    "date": commit["commit"]["author"]["date"],
                    "url": commit["html_url"]
                }
                print(commit_info)
                new_commits.append(commit_info)
            
            # 合并现有提交和新提交，并限制数量
            merged_commits = new_commits + [c for c in existing_commits if c["sha"] not in [nc["sha"] for nc in new_commits]]
            merged_commits = merged_commits[:MAX_COMMITS]
            
            # 更新Redis
            redis_client.set(REDIS_KEY, json.dumps(merged_commits))
            print(f"已将最新的提交记录缓存到Redis，键名: {REDIS_KEY}")
        else:
            print(f"没有新的提交记录")
            
        return has_new_commits
    
    except requests.RequestException as e:
        print(f"请求GitHub API失败: {e}")
        return False
    except Exception as e:
        print(f"处理提交记录时出错: {e}")
        return False

# 定义DAG参数
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args=default_args,
    description="每5分钟查询一次GitHub仓库的提交记录",
    schedule_interval="*/5 * * * *",  # 每5分钟执行一次
    catchup=False,
    tags=["github", "监控"],
)

# 定义任务
check_github_task = PythonOperator(
    task_id="check_github_commits",
    python_callable=get_latest_commits,
    provide_context=True,
    dag=dag,
)

# 设置任务依赖
check_github_task
