#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号消息监听处理DAG

功能：
1. 监听并处理来自webhook的微信公众号消息
2. 通过AI助手回复用户消息

特点：
1. 由webhook触发，不进行定时调度
2. 最大并发运行数为50
3. 支持消息分发到其他DAG处理
"""

# 标准库导入
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from threading import Thread

# 第三方库导入
import requests

# Airflow相关导入
from airflow import DAG
from airflow.api.common.trigger_dag import trigger_dag
from airflow.exceptions import AirflowException
from airflow.models import DagRun
from airflow.models.dagrun import DagRun
from airflow.models.variable import Variable
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.session import create_session
from airflow.utils.state import DagRunState

# 自定义库导入
from utils.dify_sdk import DifyAgent
from utils.redis import RedisLock
from utils.wechat_mp_channl import WeChatMPBot


DAG_ID = "wx_mp_msg_watcher"


def process_wx_message(**context):
    """
    处理微信公众号消息的任务函数, 消息分发到其他DAG处理
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 打印当前python运行的path
    print(f"当前python运行的path: {os.path.abspath(__file__)}")

    # 获取传入的消息数据
    dag_run = context.get('dag_run')
    if not (dag_run and dag_run.conf):
        print("[WATCHER] 没有收到消息数据")
        return
        
    message_data = dag_run.conf
    print("--------------------------------")
    print(json.dumps(message_data, ensure_ascii=False, indent=2))
    print("--------------------------------")

    # 获取用户信息
    mp_bot = WeChatMPBot(appid=Variable.get("WX_MP_APP_ID"), appsecret=Variable.get("WX_MP_SECRET"))
    user_info = mp_bot.get_user_info(message_data.get('FromUserName'))
    print(f"FromUserName: {message_data.get('FromUserName')}, 用户信息: {user_info}")
    # user_info = mp_bot.get_user_info(message_data.get('ToUserName'))
    # print(f"ToUserName: {message_data.get('ToUserName')}, 用户信息: {user_info}")
    
    # 判断消息类型
    msg_type = message_data.get('MsgType')
    
    if msg_type == 'text':
        return ['handler_text_msg']
    else:
        print(f"[WATCHER] 不支持的消息类型: {msg_type}")
        return []


def handler_text_msg(**context):
    """
    处理文本类消息, 通过Dify的AI助手进行聊天, 并回复微信公众号消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    
    # 提取微信公众号消息的关键信息
    to_user_name = message_data.get('ToUserName')  # 公众号原始ID
    from_user_name = message_data.get('FromUserName')  # 发送者的OpenID
    create_time = message_data.get('CreateTime')  # 消息创建时间
    content = message_data.get('Content')  # 消息内容
    msg_id = message_data.get('MsgId')  # 消息ID
    
    print(f"收到来自 {from_user_name} 的消息: {content}")
    
    # 获取微信公众号配置
    appid = Variable.get("WX_MP_APP_ID", default_var="")
    appsecret = Variable.get("WX_MP_SECRET", default_var="")
    
    if not appid or not appsecret:
        print("[WATCHER] 微信公众号配置缺失")
        return
    
    # 初始化微信公众号机器人
    mp_bot = WeChatMPBot(appid=appid, appsecret=appsecret)
    
    # 初始化dify
    dify_agent = DifyAgent(api_key=Variable.get("LUCYAI_DIFY_API_KEY"), base_url=Variable.get("DIFY_BASE_URL"))
    
    # 获取会话ID
    conversation_id = dify_agent.get_conversation_id_for_user(from_user_name)
    
    # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=content,
        user_id=from_user_name,
        conversation_id=conversation_id,
        inputs={
            "platform": "wechat_mp",
            "user_id": from_user_name,
            "msg_id": msg_id
        }
    )
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    response = full_answer
    
    if not conversation_id:
        # 新会话，重命名会话
        try:
            conversation_id = metadata.get("conversation_id")
            dify_agent.rename_conversation(conversation_id, f"微信公众号用户_{from_user_name[:8]}", "公众号对话")
        except Exception as e:
            print(f"[WATCHER] 重命名会话失败: {e}")
        
        # 保存会话ID
        conversation_infos = Variable.get("wechat_mp_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[from_user_name] = conversation_id
        Variable.set("wechat_mp_conversation_infos", conversation_infos, serialize_json=True)
    
    # 发送回复消息
    try:
        # 将长回复拆分成多条消息发送
        for response_part in re.split(r'\\n\\n|\n\n', response):
            response_part = response_part.replace('\\n', '\n')
            if response_part.strip():  # 确保不发送空消息
                mp_bot.send_text_message(from_user_name, response_part)
                time.sleep(0.5)  # 避免发送过快
        
        # 记录消息已被成功回复
        dify_msg_id = metadata.get("message_id")
        if dify_msg_id:
            dify_agent.create_message_feedback(
                message_id=dify_msg_id, 
                user_id=from_user_name, 
                rating="like", 
                content="微信公众号自动回复成功"
            )
    except Exception as error:
        print(f"[WATCHER] 发送消息失败: {error}")
        # 记录消息回复失败
        dify_msg_id = metadata.get("message_id")
        if dify_msg_id:
            dify_agent.create_message_feedback(
                message_id=dify_msg_id, 
                user_id=from_user_name, 
                rating="dislike", 
                content=f"微信公众号自动回复失败, {error}"
            )
    
    # 打印会话消息
    messages = dify_agent.get_conversation_messages(conversation_id, from_user_name)
    print("-"*50)
    for msg in messages:
        print(msg)
    print("-"*50)


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['微信公众号'],
    description='微信公众号消息监控',
)

# 创建处理消息的任务
process_message_task = BranchPythonOperator(
    task_id='process_wx_message',
    python_callable=process_wx_message,
    provide_context=True,
    dag=dag
)

# 创建处理文本消息的任务
handler_text_msg_task = PythonOperator(
    task_id='handler_text_msg',
    python_callable=handler_text_msg,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系
process_message_task >> handler_text_msg_task
