#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 wxchat_sdk 自动化微信操作的 Airflow DAG。
主要任务包括:
1. 初始化 SDK。
2. 监控聊天消息并保存到 Airflow 变量。
3. 根据网页输入发送消息。
4. 自动回复 AI 启用的聊天。

Author: Your Name
Date: 2025-01-10
"""

import time
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from dags.common.wxchat_sdk import WXAppOperator

# 获取 WXAppOperator 实例的辅助函数
def get_wx_operator():
    """获取 WXAppOperator 实例的辅助函数"""
    appium_server_url = Variable.get("appium_server_url", default_var="http://localhost:4723")
    return WXAppOperator(appium_server_url=appium_server_url)

# 获取聊天列表并保存到 Airflow Variables
def monitor_chats(**kwargs):
    """监控微信聊天列表和消息，保存到 Airflow Variables"""
    wx_operator = get_wx_operator()
    
    try:
        chat_list = wx_operator.get_current_chat_list()
        print(f"获取到的聊天列表: {chat_list}")
        chat_data = []

        for chat in chat_list:
            chat_name = chat['name']
            wx_operator.enter_chat_page(chat_name)
            time.sleep(2)  # 确保页面完全加载
            messages = wx_operator.get_chat_msg_list()
            print(f"chat_name: {chat_name}, messages: {messages}")
            chat_data.append({
                'chat_name': chat_name,
                'messages': messages
            })
            wx_operator.return_to_home_page()
        Variable.set("chat_data", chat_data)
    finally:
        wx_operator.close()  # 使用 close 方法替代 quit

# 发送消息任务
def send_messages(**kwargs):
    """根据网页输入发送消息"""
    web_input_infos = Variable.get("web_input_infos", default_var=None)
    
    if web_input_infos:
        wx_operator = get_wx_operator()
        try:
            for info in web_input_infos:
                chat_name = info['chat_name']
                message = info['message']

                wx_operator.enter_chat_page(chat_name)
                wx_operator.send_text_msg(message)
                wx_operator.return_to_home_page()

            Variable.delete("web_input_infos")  # 清除已处理的变量
        finally:
            wx_operator.close()

# AI 自动聊天任务
def ai_auto_reply(**kwargs):
    """自动回复启用 AI 的聊天"""
    enable_ai_chat_list = Variable.get("enable_ai_chat_list", default_var=None)
    
    if enable_ai_chat_list:
        wx_operator = get_wx_operator()
        try:
            for chat_name in enable_ai_chat_list:
                wx_operator.enter_chat_page(chat_name)
                time.sleep(2)  # 确保页面完全加载
                messages = wx_operator.get_chat_msg_list()

                if messages:
                    last_message = messages[-1]
                    if last_message['sender'] != 'Zacks':
                        # 触发另一个 DAG 生成回复
                        print(f"触发 AI 回复进程: {last_message}")

                wx_operator.return_to_home_page()
        finally:
            wx_operator.close()

# 定义 DAG
with DAG(
    dag_id='APPIUM_WX_BOT',
    default_args={
        'owner': 'airflow',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 1,
        'retry_delay': timedelta(minutes=1),
    },
    description='使用Appium SDK自动化微信操作',
    schedule=None,
    start_date=datetime(2025, 1, 10),
    catchup=False,
    tags=['RPA方案示例'],
) as dag:

    monitor_chats_task = PythonOperator(
        task_id='monitor_chats',
        python_callable=monitor_chats,
    )

    send_messages_task = PythonOperator(
        task_id='send_messages',
        python_callable=send_messages,
    )

    ai_auto_reply_task = PythonOperator(
        task_id='ai_auto_reply',
        python_callable=ai_auto_reply,
    )

    [monitor_chats_task, send_messages_task, ai_auto_reply_task]
