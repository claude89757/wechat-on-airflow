#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub仓库巡检DAG

功能：
1. 每5分钟查询多个GitHub仓库的提交记录
2. 如果有新的提交记录，将其缓存到最近的提交记录列表中
3. 使用Redis存储提交记录列表
4. 当有新提交时，实时推送到微信群
5. 每天晚上8点生成当日提交汇总，并推送到微信群
"""

# 标准库导入
from datetime import datetime, timedelta
import json

# 第三方库导入
import requests
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from redis import Redis

# 导入LLM功能
from utils.openrouter import OpenRouter

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
    {
        "owner": "claude89757",
        "repo": "crawler_on_airflow",
        "description": "爬虫Airflow项目"
    },
    {
        "owner": "YuChanGongzhu",
        "repo": "x_agent_webui",
        "description": "爬虫Airflow前端项目"
    },
]

# DAG ID
DAG_ID = "github_multi_repos_watcher"
DAILY_SUMMARY_DAG_ID = "github_daily_summary"

# 最大保存的提交记录数量
MAX_COMMITS = 1000



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
        
        # 获取现有提交的SHA列表，用于快速查找
        existing_commit_shas = set(commit["sha"] for commit in existing_commits)
        
        # 比较获取真正的新提交
        truly_new_commits = []
        
        for commit in commits:
            # 只处理真正的新提交（不在现有提交中的）
            if commit["sha"] not in existing_commit_shas:
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
                truly_new_commits.append(commit_info)
        
        # 检查是否有新提交
        if truly_new_commits:
            has_new_commits = True
            has_any_new_commits = True
            print(f"发现仓库 {owner}/{repo} 的新提交记录: {len(truly_new_commits)}个")
            
            # 合并现有提交和新提交，并限制数量
            merged_commits = truly_new_commits + existing_commits
            merged_commits = merged_commits[:MAX_COMMITS]
            
            # 更新Redis
            redis_client.set(redis_key, json.dumps(merged_commits))
            print(f"已将仓库 {owner}/{repo} 的最新提交记录缓存到Redis，键名: {redis_key}")
            
            # 如果有新提交，发送到微信群
            if has_new_commits:
                send_github_commits_to_wechat(truly_new_commits)
        else:
            print(f"仓库 {owner}/{repo} 没有新的提交记录")
        
    
    return has_any_new_commits


def send_github_commits_to_wechat(commits):
    """
    将GitHub提交记录发送到微信群
    
    Args:
        commits: 提交记录列表，仅包含新的提交
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
        commit_count = len(repo_data["commits"])
        msg_list.append(f"【GitHub更新】{repo_key} ({commit_count}个新提交)")
        
        # 添加每个提交的简要信息
        for commit in repo_data["commits"]:
            # 截取提交信息的第一行作为标题，并限制长度
            commit_title = commit["message"].split("\n")[0]
            if len(commit_title) > 60:
                commit_title = commit_title[:57] + "..."
            msg_list.append(f"- {commit_title} ({commit['author']})")
        
        # 最后添加第一个提交的链接
        if repo_data["commits"]:
            msg_list.append(f"\n详情: {repo_data['commits'][0]['url']}")
        
        message = '\n'.join(msg_list)
        
        # 发送消息到每个群
        chat_name = Variable.get("DEV_CHATROOM_NAME", default_var="")
        zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
        zacks_up_for_send_msg_list.append({
            "room_name": chat_name,
            "msg": message
        })
        Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)


def generate_daily_summary(**context):
    """
    生成GitHub提交记录的每日总结
    
    从Redis中获取所有仓库的提交记录，筛选出当天的提交，
    使用LLM生成中文摘要，并发送到微信群
    
    Args:
        **context: Airflow上下文参数
    
    Returns:
        None
    """
    # 连接Redis
    redis_client = Redis(host='wechat-on-airflow-redis-1', port=6379, decode_responses=True)
    
    # 获取今天的日期范围
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time()).isoformat()
    today_end = datetime.combine(today, datetime.max.time()).isoformat()
    
    print(f"正在生成 {today} 的每日提交摘要")
    print(f"日期范围: {today_start} - {today_end}")
    
    all_commits_today = []
    commit_stats_by_repo = {}
    
    # 遍历所有仓库，获取当天的提交
    for repo_config in GITHUB_REPOS:
        owner = repo_config["owner"]
        repo = repo_config["repo"]
        description = repo_config.get("description", repo)
        repo_key = f"{owner}/{repo}"
        
        # 构建Redis键
        redis_key = f"github_{owner}_{repo}_recent_commits"
        
        # 获取提交记录
        commits_json = redis_client.get(redis_key)
        if not commits_json:
            print(f"仓库 {repo_key} 没有缓存的提交记录")
            continue
        
        commits = json.loads(commits_json)
        
        # 筛选当天的提交
        today_commits = []
        for commit in commits:
            commit_date = commit.get("date", "")
            if today_start <= commit_date <= today_end:
                today_commits.append(commit)
                all_commits_today.append(commit)
        
        if today_commits:
            commit_stats_by_repo[repo_key] = {
                "description": description,
                "count": len(today_commits),
                "commits": today_commits
            }
            print(f"仓库 {repo_key} 有 {len(today_commits)} 个提交")
        else:
            print(f"仓库 {repo_key} 今天没有提交")
    
    # 如果没有今天的提交，返回
    if not all_commits_today:
        print("今天没有任何仓库有提交记录")
        chat_name = Variable.get("DEV_CHATROOM_NAME", default_var="")
        zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
        zacks_up_for_send_msg_list.append({
            "room_name": chat_name,
            "msg": f"【GitHub日报】{today}\n今天无提交记录。"
        })
        Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)
        return
    
    # 准备所有仓库的提交信息，用于生成综合摘要
    all_repos_summary = []
    
    # 为每个仓库准备提交信息
    for repo_key, repo_data in commit_stats_by_repo.items():
        try:
            # 准备LLM输入
            commits_text = "\n".join([
                f"- {commit['message']} (作者: {commit['author']}, 时间: {commit['date']})"
                for commit in repo_data["commits"]
            ])
            
            # 将仓库信息添加到综合摘要中
            all_repos_summary.append({
                "repo_key": repo_key,
                "description": repo_data["description"],
                "count": repo_data["count"],
                "commits_text": commits_text
            })
            
        except Exception as e:
            print(f"处理仓库 {repo_key} 的提交信息时出错: {e}")
    
    # 准备综合摘要的提示
    all_repos_text = "\n\n".join([
        f"仓库：{repo['repo_key']} ({repo['description']})\n提交数量：{repo['count']}\n\n提交记录：\n{repo['commits_text']}"
        for repo in all_repos_summary
    ])

    print(f"all_repos_text: {all_repos_text}")
    
    prompt = f"""作为一名技术专家，请根据以下GitHub仓库的提交记录，生成一份综合性的开发日报摘要。
日期：{today}

{all_repos_text}

要求：
1. 体现每个团队成员的贡献，不要遗漏
2. 以团队整体开发进展为视角，提取所有仓库的关键变更点（总计3-5点）
3. 按重要性排序，重点突出功能新增、架构改进、问题修复等内容
4. 使用专业技术术语，简明扼要描述变更要点
5. 适当使用项目符号提高可读性
6. 可根据实际情况灵活组织内容结构

总结必须简洁明了，控制在250字以内，突出团队整体进展。"""

    # 调用LLM生成综合摘要
    api_key = Variable.get("OPENROUTER_API_KEY")
    openrouter = OpenRouter(api_key=api_key)
    response = openrouter.chat_completion(
        messages=[
            {"role": "system", "content": prompt}
        ],
        model="openai/gpt-4o-mini"
    )
    summary = openrouter.extract_text_response(response)
    
    if not summary:
        print("生成综合摘要失败")
        return
    
    # 发送综合摘要到微信群
    chat_name = Variable.get("DEV_CHATROOM_NAME", default_var="")
    zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
    zacks_up_for_send_msg_list.append({
        "room_name": chat_name,
        "msg": f"【GitHub日报】{today}\n{summary}"
    })
    Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)

# 定义实时监控DAG参数
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

# 创建实时监控DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args=default_args,
    description="每5分钟查询多个GitHub仓库的提交记录",
    schedule_interval="*/10 * * * *",  # 每10分钟执行一次
    catchup=False,
    tags=["github", "监控"],
)

# 定义实时监控任务
check_github_task = PythonOperator(
    task_id="check_github_commits",
    python_callable=get_latest_commits,
    provide_context=True,
    dag=dag,
)

# 设置实时监控任务依赖
check_github_task

# 定义每日总结DAG参数
daily_summary_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

# 创建每日总结DAG
daily_summary_dag = DAG(
    dag_id=DAILY_SUMMARY_DAG_ID,
    default_args=daily_summary_args,
    description="每天晚上8点生成GitHub提交记录的每日总结",
    schedule_interval="0 20 * * *",  # 每天晚上8点执行
    catchup=False,
    tags=["github", "日报"],
)

# 定义每日总结任务
daily_summary_task = PythonOperator(
    task_id="generate_daily_summary",
    python_callable=generate_daily_summary,
    provide_context=True,
    dag=daily_summary_dag,
)

# 设置每日总结任务依赖
daily_summary_task
