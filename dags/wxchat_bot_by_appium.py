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
from dags.sdk.wxchat_sdk import WXAppOperator


# 初始化 SDK 实例的函数
def init_sdk(**kwargs):
    """Initialize the WeChat SDK instance and push it to XCom."""
    appium_server_url = Variable.get("appium_server_url", default_var="http://localhost:4723")
    wx_operator = WXAppOperator(appium_server_url=appium_server_url)
    kwargs['ti'].xcom_push(key='wx_operator', value=wx_operator)

# 获取聊天列表并保存到 Airflow Variables
def monitor_chats(**kwargs):
    """Monitor WeChat chat lists and messages, saving them to Airflow Variables."""
    ti = kwargs['ti']
    wx_operator = ti.xcom_pull(task_ids='init_sdk', key='wx_operator')

    if not wx_operator:
        raise ValueError("SDK instance was not initialized correctly.")

    chat_list = wx_operator.get_current_chat_list()
    chat_data = []

    for chat in chat_list:
        chat_name = chat['name']
        wx_operator.enter_chat_page(chat_name)
        time.sleep(2)  # Ensure the page is fully loaded
        messages = wx_operator.get_chat_msg_list()
        chat_data.append({
            'chat_name': chat_name,
            'messages': messages
        })
        wx_operator.return_to_home_page()

    Variable.set("chat_data", chat_data)

# 发送消息任务
def send_messages(**kwargs):
    """Send messages based on the web input stored in Airflow Variables."""
    web_input_infos = Variable.get("web_input_infos", default_var=None)

    if web_input_infos:
        wx_operator = kwargs['ti'].xcom_pull(task_ids='init_sdk', key='wx_operator')

        for info in web_input_infos:
            chat_name = info['chat_name']
            message = info['message']

            wx_operator.enter_chat_page(chat_name)
            wx_operator.send_text_msg(message)
            wx_operator.return_to_home_page()

        Variable.delete("web_input_infos")  # Clear processed variable

# AI 自动聊天任务
def ai_auto_reply(**kwargs):
    """Automatically reply to messages in AI-enabled chats."""
    enable_ai_chat_list = Variable.get("enable_ai_chat_list", default_var=None)

    if enable_ai_chat_list:
        wx_operator = kwargs['ti'].xcom_pull(task_ids='init_sdk', key='wx_operator')

        for chat_name in enable_ai_chat_list:
            wx_operator.enter_chat_page(chat_name)
            time.sleep(2)  # Ensure the page is fully loaded
            messages = wx_operator.get_chat_msg_list()

            if messages:
                last_message = messages[-1]
                if last_message['sender'] != 'Zacks':
                    # Trigger another DAG to generate a reply
                    # Use TriggerDagRunOperator or custom triggering logic here
                    print(f"Triggering AI reply process: {last_message}")

            wx_operator.return_to_home_page()

# 定义 DAG
with DAG(
    dag_id='wxchat_bot',
    default_args={
        'owner': 'airflow',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 1,
        'retry_delay': timedelta(minutes=1),
    },
    description='WeChat automation tasks using wxchat_sdk',
    schedule=None,
    start_date=datetime(2025, 1, 10),
    catchup=False,
    tags=['RPA方案示例'],
) as dag:

    init_sdk_task = PythonOperator(
        task_id='init_sdk',
        python_callable=init_sdk,
    )

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

    init_sdk_task >> [monitor_chats_task, send_messages_task, ai_auto_reply_task]
