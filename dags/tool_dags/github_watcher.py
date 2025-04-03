#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub仓库巡检DAG

功能：
1. 每5分钟查询多个GitHub仓库的提交记录
2. 如果有新的提交记录，将其缓存到最近的提交记录列表中
3. 使用Redis存储提交记录列表
4. 当有新提交时，实时推送到微信群
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

# 导入微信消息发送功能
from utils.wechat_channl import send_wx_msg

# 从Airflow变量获取仓库配置
GITHUB_REPOS = [
    {
        "owner": "claude89757",
        "repo": "wechat-on-airflow",
        "description": "微信Airflow项目"
    },
    {
        "owner": "YuChanGongzhu",
        "repo": "ai-agent",
        "description": "前端项目"
    },
    
]

# DAG ID
DAG_ID = "github_repos_watcher"

# 最大保存的提交记录数量
MAX_COMMITS = 20

# 微信配置
WECHAT_CONFIG = {
    "DEV_WCF_IP": Variable.get("DEV_WCF_IP", default_var="10.1.8.5"),
    "GITHUB_ROOM_ID_LIST": Variable.get("GITHUB_ROOM_ID_LIST", deserialize_json=True, default_var=["57852893888@chatroom"])
}

def get_latest_commits(**context):
    """
    从GitHub获取多个仓库的最新提交记录
    
    Args:
        **context: Airflow上下文参数
    
    Returns:
        None
    """
    has_any_new_commits = False
    
    # 连接Redis
    redis_client = Redis(host='wechat-on-airflow-redis-1', port=6379, decode_responses=True)
    
    # 遍历监控的GitHub仓库列表
    for repo_config in GITHUB_REPOS:
        owner = repo_config["owner"]
        repo = repo_config["repo"]
        description = repo_config.get("description", repo)
        
        print(f"正在检查仓库: {owner}/{repo}")
        
        # 为每个仓库构建唯一的Redis键
        redis_key = f"github_{owner}_{repo}_recent_commits"
        
        try:
            # 构建API URL
            api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
            
            # 设置请求头
            headers = {
                "Accept": "application/vnd.github.v3+json"
            }
            
            # 请求GitHub API
            response = requests.get(api_url, headers=headers, params={"per_page": 10})
            response.raise_for_status()
            
            # 解析响应
            commits = response.json()
            
            if not commits or not isinstance(commits, list):
                print(f"未获取到仓库 {owner}/{repo} 的有效提交记录")
                continue
            
            # 获取现有的提交记录
            existing_commits_json = redis_client.get(redis_key)
            existing_commits = json.loads(existing_commits_json) if existing_commits_json else []
            
            # 检查是否有新提交
            latest_commit_sha = commits[0]["sha"]
            
            # 如果没有现有提交或者最新提交与缓存中的不同，则更新缓存
            new_commits = []
            
            if not existing_commits or latest_commit_sha != existing_commits[0]["sha"]:
                has_new_commits = True
                has_any_new_commits = True
                print(f"发现仓库 {owner}/{repo} 的新提交记录，SHA: {latest_commit_sha}")
                
                # 提取需要保存的提交信息
                for commit in commits:
                    commit_info = {
                        "sha": commit["sha"],
                        "message": commit["commit"]["message"],
                        "author": commit["commit"]["author"]["name"],
                        "date": commit["commit"]["author"]["date"],
                        "url": commit["html_url"],
                        "owner": owner,
                        "repo": repo,
                        "description": description
                    }
                    print(commit_info)
                    new_commits.append(commit_info)
                
                # 合并现有提交和新提交，并限制数量
                merged_commits = new_commits + [c for c in existing_commits if c["sha"] not in [nc["sha"] for nc in new_commits]]
                merged_commits = merged_commits[:MAX_COMMITS]
                
                # 更新Redis
                redis_client.set(redis_key, json.dumps(merged_commits))
                print(f"已将仓库 {owner}/{repo} 的最新提交记录缓存到Redis，键名: {redis_key}")
                
                # 如果有新提交，发送到微信群
                if has_new_commits and WECHAT_CONFIG["WCF_IP"] and WECHAT_CONFIG["GITHUB_ROOM_ID_LIST"]:
                    send_github_commits_to_wechat(new_commits)
            else:
                print(f"仓库 {owner}/{repo} 没有新的提交记录")
        
        except requests.RequestException as e:
            print(f"请求仓库 {owner}/{repo} 的GitHub API失败: {e}")
        except Exception as e:
            print(f"处理仓库 {owner}/{repo} 的提交记录时出错: {e}")
    
    return has_any_new_commits


def send_github_commits_to_wechat(commits):
    """
    将GitHub提交记录发送到微信群
    
    Args:
        commits: 提交记录列表
    """
    if not commits:
        return
    
    # 按仓库分组提交记录
    commits_by_repo = {}
    for commit in commits:
        repo_key = f"{commit['owner']}/{commit['repo']}"
        if repo_key not in commits_by_repo:
            commits_by_repo[repo_key] = {
                "commits": [],
                "owner": commit["owner"],
                "repo": commit["repo"],
                "description": commit.get("description", commit["repo"])
            }
        commits_by_repo[repo_key]["commits"].append(commit)
    
    # 为每个仓库生成消息
    for repo_key, repo_data in commits_by_repo.items():
        # 简洁的消息
        msg_list = []
        msg_list.append(f"【GitHub更新】{repo_key}")
        
        # 添加每个提交的简要信息
        for commit in repo_data["commits"]:
            # 截取提交信息的第一行作为标题
            commit_title = commit["message"].split("\n")[0]
            msg_list.append(f"- {commit_title} ({commit['author']})")
        
        # 最后添加第一个提交的链接
        if repo_data["commits"]:
            msg_list.append(f"\n详情: {repo_data['commits'][0]['url']}")
        
        message = '\n'.join(msg_list)
        
        # 发送消息到每个群
        for room_id in WECHAT_CONFIG["GITHUB_ROOM_ID_LIST"]:
            try:
                send_wx_msg(
                    wcf_ip=WECHAT_CONFIG["DEV_WCF_IP"],
                    message=message,
                    receiver=room_id,
                    aters=''
                )
                print(f"已发送仓库 {repo_key} 的GitHub提交记录到微信群: {room_id}")
            except Exception as e:
                print(f"发送仓库 {repo_key} 的GitHub提交记录到微信群失败: {e}")


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
    description="每5分钟查询多个GitHub仓库的提交记录",
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
