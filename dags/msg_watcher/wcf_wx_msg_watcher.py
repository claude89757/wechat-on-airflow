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

# 标准库导入
import json
import os
import re
from datetime import datetime, timedelta, timezone
import time

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.api.common.trigger_dag import trigger_dag
from airflow.models.dagrun import DagRun
from airflow.utils.state import DagRunState
from airflow.models.variable import Variable
from airflow.utils.session import create_session

from utils.wechat_channl import send_wx_msg
from utils.redis import RedisLock


def excute_wx_command(content: str, room_id: str, sender: str, source_ip: str) -> bool:
    """执行命令"""
    if content.replace('@Zacks', '').strip().lower() == 'clear':
        print("[命令] 清理历史消息")
        Variable.delete(f'{room_id}_history')
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已清理历史消息', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai off':
        print("[命令] 禁用AI聊天")
        Variable.set(f'{room_id}_disable_ai', True, serialize_json=True)
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已禁用AI聊天', receiver=room_id)
        return True
    elif content.replace('@Zacks', '').strip().lower() == 'ai on':
        print("[命令] 启用AI聊天")
        Variable.delete(f'{room_id}_disable_ai')
        send_wx_msg(wcf_ip=source_ip, message=f'[bot] {room_id} 已启用AI聊天', receiver=room_id)
        return True
    return False


def process_wx_message(**context):
    """
    处理微信消息的任务函数, 消息分发到其他DAG处理
    
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
    
    # 读取消息参数
    room_id = message_data.get('roomid')
    formatted_roomid = re.sub(r'[^a-zA-Z0-9]', '', str(room_id))  # 用于触发DAG的run_id
    sender = message_data.get('sender')
    msg_id = message_data.get('id')
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_group = message_data.get('is_group', False)  # 是否群聊
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 执行命令
    if excute_wx_command(content, room_id, sender, source_ip):
        return
    
    # 检查room_id是否在AI黑名单中
    if Variable.get(f'{room_id}_disable_ai', default_var=False, deserialize_json=True):
        print(f"[WATCHER] {room_id} 已禁用AI聊天，停止处理")
        return
    
    # 开启全局群聊的room_id
    enable_ai_room_ids = Variable.get('enable_ai_room_ids', default_var=[], deserialize_json=True)
  
    # 分类处理
    if msg_type == 1 and ((content.startswith('@Zacks') or not is_group) 
                          or (is_group and room_id in enable_ai_room_ids)):
        # 缓存收到需要回复的消息类型
        room_sender_msg_list = Variable.get(f'{room_id}_{sender}_msg_list', default_var=[], deserialize_json=True)
        if room_sender_msg_list and message_data['id'] != room_sender_msg_list[-1]['id']:
            room_sender_msg_list.append(message_data)
            Variable.set(f'{room_id}_{sender}_msg_list', room_sender_msg_list, serialize_json=True)
        else:
            pass

        if room_sender_msg_list[-1]['reply_status'] == False:
            # 消息未回复, 触发新的DAG运行agent
            now = datetime.now(timezone.utc)
            execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)  # 添加随机毫秒延迟
            run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'
            print(f"[WATCHER] 触发AI聊天DAG，run_id: {run_id}")
            trigger_dag(
                dag_id='dify_agent_001',
                conf={"current_message": message_data},
                run_id=run_id,
                execution_date=execution_date
            )
            print(f"[WATCHER] 成功触发AI聊天DAG，execution_date: {execution_date}")
        else:
            print(f"[WATCHER] 消息已回复，不重复触发AI聊天DAG")
    else:
        # 非文字消息，暂不触发AI聊天流程
        print("[WATCHER] 不触发AI聊天流程")

# 创建DAG
dag = DAG(
    dag_id='wx_msg_watcher',
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 0,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=30,
    catchup=False,
    tags=['WCF-微信消息监控'],
    description='WCF-微信消息监控',
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
