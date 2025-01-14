#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI聊天处理DAG

功能：
1. 处理用户与AI助手的对话
2. 支持gpt-4-mini模型对话
3. 接收来自wx_msg_watcher的消息触发

特点：
1. 由wx_msg_watcher触发，不进行定时调度
2. 最大并发运行数为5
3. 支持异常重试
"""

# Python标准库
from datetime import datetime, timedelta
import json
import os
from typing import Dict, Any

# 第三方库
from airflow import DAG
from airflow.operators.python import PythonOperator
from openai import OpenAI
import requests
from airflow.models import Variable

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(seconds=10),
}

def send_message_to_wx(message: str, receiver: str, aters: str = "") -> bool:
    """发送消息到微信"""
    wx_api_url = Variable.get("WX_API_URL")
    endpoint = f"{wx_api_url}/text"
    
    print(f"[WX] 发送消息 -> {receiver} {'@'+aters if aters else ''}")
    print(f"[WX] 内容: {message}")
    
    try:
        payload = {
            "msg": message,
            "receiver": receiver,
            "aters": aters
        }
        
        response = requests.post(
            endpoint,
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        print(f"[WX] 响应: {response.status_code} - {response.text}")
        
        response.raise_for_status()
        
        result = response.json()
        if result.get('status') != 0:
            raise Exception(f"发送失败: {result.get('message', '未知错误')}")
        
        print("[WX] 发送成功")    
        return True
        
    except requests.exceptions.RequestException as e:
        error_msg = f"发送失败: {str(e)}"
        print(error_msg)
        raise Exception(error_msg)

def process_ai_chat(**context):
    """
    处理AI聊天的任务函数
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 获取消息数据
    dag_run = context.get('dag_run')
    if not (dag_run and dag_run.conf):
        print("[CHAT] 没有收到消息数据")
        return
        
    message_data = dag_run.conf
    print(f"[CHAT] 收到消息数据: {json.dumps(message_data, ensure_ascii=False)}")
    
    content = message_data.get('content', '')
    sender = message_data.get('sender', '')  # 发送者ID
    room_id = message_data.get('roomid', '')  # 群聊ID
    is_group = message_data.get('is_group', False)  # 是否群聊
    
    # 提取@Zacks后的实际问题内容
    question = content.replace('@Zacks', '').strip()
    if not question:
        print("[CHAT] 没有检测到实际问题内容")
        return
        
    try:
        # 调用AI接口获取回复
        response = call_ai_api(question)
        print(f"[CHAT] AI回复: {response}")
        
        # 确定消息接收者
        if not room_id:
            raise Exception("无法确定消息接收者：roomid为空")
            
        # 统一使用room_id作为接收者
        receiver = room_id
        
        # 构造回复消息
        if is_group:
            # 群聊中需要@发送者
            reply_message = f"@{sender}\n{response}"
            aters = sender
        else:
            # 单聊直接发送回复
            reply_message = response
            aters = ""
        
        print(f"[CHAT] 发送回复到: {receiver} (群聊: {is_group})")
        
        # 发送消息
        success = send_message_to_wx(
            message=reply_message,
            receiver=receiver,
            aters=aters
        )
        
        if success:
            print(f"[CHAT] 成功发送回复到{'群聊' if is_group else '私聊'}")
        
    except Exception as e:
        print(f"[CHAT] 处理AI聊天时发生错误: {str(e)}")
        raise

def get_system_prompt() -> str:
    """
    从Airflow Variable获取系统prompt配置
    
    Returns:
        str: 系统prompt内容，如果未配置则返回默认值
    """
    try:
        return Variable.get(
            "ai_chat_system_prompt",
            default_var="你是一个友好的AI助手，请用简短的中文回答问题。"
        )
    except Exception as e:
        print(f"获取系统prompt配置失败: {str(e)}，使用默认配置")
        return "你是一个友好的AI助手，请用简短的中文回答问题。"

def call_ai_api(question: str) -> str:
    """调用ChatGPT API进行对话"""
    print(f"[AI] 问题: {question}")
    
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')
    
    try:
        api_key = Variable.get("OPENAI_API_KEY")
        proxy_url = Variable.get("OPENAI_PROXY_URL")
        proxy_user = Variable.get("OPENAI_PROXY_USER")
        proxy_pass = Variable.get("OPENAI_PROXY_PASS")
        
        os.environ['OPENAI_API_KEY'] = api_key
        proxy = f"https://{proxy_user}:{proxy_pass}@{proxy_url}"
        os.environ['HTTPS_PROXY'] = proxy
        os.environ['HTTP_PROXY'] = proxy
        
        client = OpenAI()
        system_prompt = get_system_prompt()
        print(f"[AI] 系统提示: {system_prompt}")
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.5,
            max_tokens=500,
            top_p=0.8,
            frequency_penalty=0.3,
            presence_penalty=0.3
        )
        
        ai_response = response.choices[0].message.content.strip()
        print(f"[AI] 回复: {ai_response}")
        return ai_response
        
    except Exception as e:
        error_msg = f"API调用失败: {str(e)}"
        print(f"[AI] {error_msg}")
        raise Exception(error_msg)
    finally:
        if original_http_proxy:
            os.environ['HTTP_PROXY'] = original_http_proxy
        else:
            os.environ.pop('HTTP_PROXY', None)
            
        if original_https_proxy:
            os.environ['HTTPS_PROXY'] = original_https_proxy
        else:
            os.environ.pop('HTTPS_PROXY', None)

# 创建DAG
dag = DAG(
    'ai_chat',
    default_args=default_args,
    description='处理AI聊天的DAG',
    schedule_interval=None,  # 仅由wx_msg_watcher触发
    max_active_runs=3,
    catchup=False,
    tags=['AI助手']
)

# 创建处理AI聊天的任务
process_chat = PythonOperator(
    task_id='process_ai_chat',
    python_callable=process_ai_chat,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系
process_chat 