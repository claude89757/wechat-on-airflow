#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息发送DAG

功能：
1. 接收消息内容和目标接收者
2. 通过WCF API发送消息
3. 支持@群成员

特点：
1. 按需触发执行
2. 最大并发运行数为1
3. 支持发送文本消息
4. 超时时间1分钟
"""

# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import send_wx_msg


DAG_ID = "wx_msg_sender"


def check_wx_account_status(**context):
    """
    检查微信账号状态
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 输入数据
    input_data = context.get('dag_run').conf
    print(f"输入数据: {input_data}")
    up_for_send_msg = input_data['msg']
    source_ip = input_data['source_ip']
    room_id = input_data['room_id']
    aters = input_data.get('aters', '')

    # 发送文本消息
    send_wx_msg(wcf_ip=source_ip, message=up_for_send_msg, receiver=room_id, aters=aters)

    # TODO(claude89757): 增加支持发送图片/视频/文件等


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    dagrun_timeout=timedelta(minutes=1),
    catchup=False,
    tags=['微信工具', '发送消息'],
    description='微信消息发送',
)

# 创建处理消息的任务
check_wx_account_status_task = PythonOperator(
    task_id='check_wx_account_status',
    python_callable=check_wx_account_status,
    provide_context=True,
    dag=dag
)
