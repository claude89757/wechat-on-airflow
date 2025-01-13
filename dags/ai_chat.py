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
    'retry_delay': timedelta(minutes=5),
}

def send_message_to_wx(message: str, receiver: str, aters: str = "") -> bool:
    """
    发送消息到微信
    
    Args:
        message: 要发送的消息内容
        receiver: 接收者的wxid或群id
        aters: 要@的用户wxid，多个用逗号分隔，@所有人使用notify@all
        
    Returns:
        bool: 发送是否成功
        
    Raises:
        Exception: 发送消息失败时抛出异常
    """
    wx_api_url = os.getenv('WX_API_URL', 'http://127.0.0.1:9999')
    endpoint = f"{wx_api_url}/text"
    
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
        response.raise_for_status()
        
        result = response.json()
        if result.get('status') != 'success':
            raise Exception(f"发送消息失败: {result.get('message', '未知错误')}")
            
        return True
        
    except requests.exceptions.RequestException as e:
        error_msg = f"发送消息到微信接口失败: {str(e)}"
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
        print("没有收到消息数据")
        return
        
    message_data = dag_run.conf
    content = message_data.get('content', '')
    room_id = message_data.get('room_id', '')  # 群聊ID，单聊时为空
    from_id = message_data.get('from_id', '')  # 发送者ID
    
    # 提取@Zacks后的实际问题内容
    question = content.replace('@Zacks', '').strip()
    if not question:
        print("没有检测到实际问题内容")
        return
        
    try:
        # 调用AI接口获取回复
        response = call_ai_api(question)
        print(f"AI回复: {response}")
        
        # 确定消息接收者和是否需要@
        receiver = room_id if room_id else from_id  # 群聊发给群，单聊发给个人
        
        # 构造回复消息
        if room_id:
            # 群聊中需要@发送者
            reply_message = f"@{from_id}\n{response}"
            aters = from_id
        else:
            # 单聊直接发送回复
            reply_message = response
            aters = ""
        
        # 发送消息
        success = send_message_to_wx(
            message=reply_message,
            receiver=receiver,
            aters=aters
        )
        
        if success:
            print(f"成功发送回复到{'群聊' if room_id else '私聊'}")
        
    except Exception as e:
        print(f"处理AI聊天时发生错误: {str(e)}")
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
    """
    调用ChatGPT API进行对话，使用轻量级模型
    
    Args:
        question: 用户问题
        
    Returns:
        str: AI的回复
        
    Raises:
        Exception: API调用失败时抛出异常
    """
    try:
        # 从Airflow Variable获取OpenAI API密钥
        api_key = Variable.get("OPENAI_API_KEY")
        
        # 初始化OpenAI客户端
        client = OpenAI(api_key=api_key)
        
        # 获取系统prompt配置
        system_prompt = get_system_prompt()
        
        # 调用ChatGPT API，使用轻量级模型
        response = client.chat.completions.create(
            model="gpt-4-mini",  # 使用最新的轻量级模型
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.5,  # 降低创造性，使回答更加确定
            max_tokens=500,   # 限制回答长度，减少token消耗
            top_p=0.8,
            frequency_penalty=0.3,  # 增加词语多样性
            presence_penalty=0.3    # 增加主题多样性
        )
        
        # 提取AI回复
        ai_response = response.choices[0].message.content.strip()
        return ai_response
        
    except Exception as e:
        error_msg = f"调用AI API时发生错误: {str(e)}"
        print(error_msg)
        raise Exception(error_msg)

# 创建DAG
dag = DAG(
    'ai_chat',
    default_args=default_args,
    description='处理AI聊天的DAG',
    schedule_interval=None,  # 仅由wx_msg_watcher触发
    max_active_runs=5,
    catchup=False
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