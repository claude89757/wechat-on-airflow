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
    wx_api_url = Variable.get("WX_API_URL")
    endpoint = f"{wx_api_url}/text"
    
    print(f"[WX] 准备发送消息到微信")
    print(f"[WX] API地址: {endpoint}")
    print(f"[WX] 接收者: {receiver}")
    print(f"[WX] @用户: {aters if aters else '无'}")
    print(f"[WX] 消息内容: {message}")
    
    try:
        payload = {
            "msg": message,
            "receiver": receiver,
            "aters": aters
        }
        
        print(f"[WX] 发送请求: {json.dumps(payload, ensure_ascii=False)}")
        
        response = requests.post(
            endpoint,
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        print(f"[WX] 响应状态码: {response.status_code}")
        print(f"[WX] 响应内容: {response.text}")
        
        response.raise_for_status()
        
        result = response.json()
        if result.get('status') != 'success':
            raise Exception(f"发送消息失败: {result.get('message', '未知错误')}")
        
        print("[WX] 消息发送成功")    
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
        print("[CHAT] 没有收到消息数据")
        return
        
    message_data = dag_run.conf
    print(f"[CHAT] 收到消息数据: {json.dumps(message_data, ensure_ascii=False)}")
    
    content = message_data.get('content', '')
    room_id = message_data.get('room_id', '')  # 群聊ID，单聊时为空
    from_id = message_data.get('from_id', '')  # 发送者ID
    
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
        if not (room_id or from_id):
            raise Exception("无法确定消息接收者：群ID和发送者ID都为空")
            
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
        
        print(f"[CHAT] 发送回复到: {receiver} (群聊: {bool(room_id)})")
        
        # 发送消息
        success = send_message_to_wx(
            message=reply_message,
            receiver=receiver,
            aters=aters
        )
        
        if success:
            print(f"[CHAT] 成功发送回复到{'群聊' if room_id else '私聊'}")
        
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
    """
    调用ChatGPT API进行对话，使用轻量级模型
    
    Args:
        question: 用户问题
        
    Returns:
        str: AI的回复
        
    Raises:
        Exception: API调用失败时抛出异常
    """
    print(f"[AI] 准备调用AI接口")
    print(f"[AI] 问题内容: {question}")
    
    # 保存原始环境变量
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')
    
    try:
        # 从Airflow Variable获取配置
        api_key = Variable.get("OPENAI_API_KEY")
        proxy_url = Variable.get("OPENAI_PROXY_URL")  # 代理地址
        proxy_user = Variable.get("OPENAI_PROXY_USER")  # 代理用户名
        proxy_pass = Variable.get("OPENAI_PROXY_PASS")  # 代理密码
        
        print(f"[AI] 代理地址: {proxy_url}")
        print(f"[AI] 代理用户: {proxy_user}")
        
        # 临时设置环境变量
        os.environ['OPENAI_API_KEY'] = api_key
        proxy = f"https://{proxy_user}:{proxy_pass}@{proxy_url}"
        os.environ['HTTPS_PROXY'] = proxy
        os.environ['HTTP_PROXY'] = proxy
        
        print("[AI] 环境变量设置完成")
        
        # 初始化OpenAI客户端
        client = OpenAI()
        
        # 获取系统prompt配置
        system_prompt = get_system_prompt()
        print(f"[AI] 系统Prompt: {system_prompt}")
        
        # 调用ChatGPT API，使用轻量级模型
        print("[AI] 开始调用API...")
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
        
        # 提取AI回复
        ai_response = response.choices[0].message.content.strip()
        print(f"[AI] 获得回复: {ai_response}")
        return ai_response
        
    except Exception as e:
        error_msg = f"调用AI API时发生错误: {str(e)}"
        print(f"[AI] {error_msg}")
        raise Exception(error_msg)
    finally:
        print("[AI] 开始恢复环境变量")
        # 恢复原始环境变量
        if original_http_proxy:
            os.environ['HTTP_PROXY'] = original_http_proxy
            print(f"[AI] 已恢复HTTP_PROXY: {original_http_proxy}")
        else:
            os.environ.pop('HTTP_PROXY', None)
            print("[AI] 已移除HTTP_PROXY")
            
        if original_https_proxy:
            os.environ['HTTPS_PROXY'] = original_https_proxy
            print(f"[AI] 已恢复HTTPS_PROXY: {original_https_proxy}")
        else:
            os.environ.pop('HTTPS_PROXY', None)
            print("[AI] 已移除HTTPS_PROXY")
        print("[AI] 环境变量恢复完成")

# 创建DAG
dag = DAG(
    'ai_chat',
    default_args=default_args,
    description='处理AI聊天的DAG',
    schedule_interval=None,  # 仅由wx_msg_watcher触发
    max_active_runs=3,
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