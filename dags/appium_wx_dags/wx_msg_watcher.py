#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Appium 自动化微信操作的流程
Author: claude89757
Date: 2025-04-22
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

from utils.wx_appium_for_sony import get_recent_new_msg_by_appium
from utils.wx_appium_for_sony import send_wx_msg_by_appium


def monitor_chats(**context):
    """监控聊天消息"""
    print("监控聊天消息")

    # 获取最近的新消息
    recent_new_msg = get_recent_new_msg_by_appium()
    print(recent_new_msg)
    
    # 缓存到XCOM
    context['ti'].xcom_push(key='recent_new_msg', value=recent_new_msg)

    return recent_new_msg


def send_messages(**context):
    """发送消息"""
    print("发送消息")

    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key='recent_new_msg')
    print(recent_new_msg)
    
    # 发送消息
    for contact_name, messages in recent_new_msg.items():
        send_wx_msg_by_appium(contact_name, f"测试: 我收到了{len(messages)}条消息")

    return recent_new_msg

# 定义 DAG
with DAG(
    dag_id='appium_wx_msg_watcher',
    default_args={
        'owner': 'claude89757',
        'retries': 1,
        'retry_delay': timedelta(seconds=5),
    },
    description='使用Appium SDK自动化微信操作',
    schedule=timedelta(seconds=10),
    start_date=datetime(2025, 1, 10),
    catchup=False,
    tags=['测试示例'],
) as dag:

    monitor_chats_task = PythonOperator(
        task_id='monitor_chats',
        python_callable=monitor_chats,
    )

    send_messages_task = PythonOperator(
        task_id='send_messages',
        python_callable=send_messages,
    )

    monitor_chats_task >> send_messages_task
