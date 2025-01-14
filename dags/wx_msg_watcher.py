#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息监听处理DAG

功能：
1. 监听并处理来自webhook的微信消息
2. 当收到@Zacks的消息时，触发AI聊天DAG

特点：
1. 由webhook触发，不进行定时调度
2. 最大并发运行数为10
3. 支持消息分发到其他DAG处理
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import json
from airflow.api.common.trigger_dag import trigger_dag

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
    """
    # 获取传入的消息数据
    dag_run = context.get('dag_run')
    if not (dag_run and dag_run.conf):
        print("[WATCHER] 没有收到消息数据")
        return
        
    message_data = dag_run.conf
    print("[WATCHER] 收到微信消息:")
    print("[WATCHER] 消息类型:", message_data.get('type'))
    print("[WATCHER] 消息内容:", message_data.get('content'))
    print("[WATCHER] 发送者:", message_data.get('sender'))
    print("[WATCHER] 群聊ID:", message_data.get('roomid'))
    print("[WATCHER] 是否群聊:", message_data.get('is_group'))
    print("[WATCHER] 完整消息数据:")
    print("--------------------------------")
    print(json.dumps(message_data, ensure_ascii=False, indent=2))
    print("--------------------------------")
    
    # 检查是否需要触发AI聊天
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_group = message_data.get('is_group', False)  # 是否群聊
    
    if msg_type == 1 and content.startswith('@Zacks') and is_group:
        print("[WATCHER] 群聊消息触发AI聊天流程")
        
        # 触发ai_chat DAG，并传递完整的消息数据
        run_id = f'ai_chat_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        print(f"[WATCHER] 触发AI聊天DAG，run_id: {run_id}")
            
        trigger_dag(
            dag_id='ai_chat',
            conf=message_data,
            run_id=run_id
        )
    elif msg_type == 1 and not is_group:
        print("[WATCHER] 私聊消息触发AI聊天流程")   

        # 触发ai_chat DAG，并传递完整的消息数据
        run_id = f'ai_chat_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        print(f"[WATCHER] 触发AI聊天DAG，run_id: {run_id}")
            
        trigger_dag(
            dag_id='ai_chat',
            conf=message_data,
            run_id=run_id
        )
    else:
        print("[WATCHER] 不触发AI聊天流程")

# 创建DAG
dag = DAG(
    'wx_msg_watcher',
    default_args=default_args,
    description='监控并处理微信消息的DAG',
    schedule_interval=None,  # 不设置调度，仅由webhook触发
    max_active_runs=10,  # 最多同时运行10个实例
    catchup=False,
    tags=['微信消息监控']
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
