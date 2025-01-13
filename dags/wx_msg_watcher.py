#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息处理DAG
功能：接收并处理来自webhook的微信消息
特点：
1. 由webhook触发，不进行定时调度
2. 最大并发运行数为10
3. 当前功能为接收消息并打印
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import json

# DAG默认参数
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def process_wx_message(**context):
    """
    处理微信消息的任务函数
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
        
    Returns:
        None
        
    说明：
        - 从dag_run.conf中获取webhook传入的消息数据
        - 将消息内容格式化打印
    """
    # 获取传入的消息数据
    dag_run = context.get('dag_run')
    if dag_run and dag_run.conf:
        message_data = dag_run.conf
        print("收到微信消息:")
        print(json.dumps(message_data, ensure_ascii=False, indent=2))
    else:
        print("没有收到消息数据")

# 创建DAG
dag = DAG(
    'wx_msg_watcher',
    default_args=default_args,
    description='监控并处理微信消息的DAG',
    schedule_interval=None,  # 不设置调度，仅由webhook触发
    max_active_runs=10,  # 最多同时运行10个实例
    catchup=False
)

# 创建处理消息的任务
process_message = PythonOperator(
    task_id='process_wx_message',
    python_callable=process_wx_message,
    provide_context=True,
    dag=dag
)

# 设置任务依赖关系（当前只有一个任务，所以不需要设置依赖）
process_message
