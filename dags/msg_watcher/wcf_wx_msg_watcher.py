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
    
    # 分类处理
    if msg_type == 1 and (content.startswith('@Zacks') or not is_group):

        # 缓存聊天的历史消息
        room_history = Variable.get(f'{room_id}_history', default_var=[], deserialize_json=True)
        simple_message_data = {
            'roomid': room_id,
            'formatted_roomid': formatted_roomid,
            'sender': sender,
            'id': msg_id,
            'content': content,
            'is_group': is_group,
            'ts': current_msg_timestamp,
            'is_ai_msg': False
        }
        room_history.append(simple_message_data)
        Variable.set(f'{room_id}_history', room_history, serialize_json=True)

        # 查询已触发的排队中和正在运行的DAGRun
        active_runs = DagRun.find(
            dag_id='zacks_ai_agent',
            state=DagRunState.RUNNING,  # 先查询RUNNING状态
        )
        queued_runs = DagRun.find(
            dag_id='zacks_ai_agent',
            state=DagRunState.QUEUED,  # 再查询QUEUED状态
        )
        all_active_runs = active_runs + queued_runs
        same_room_sender_runs = [run for run in all_active_runs if run.run_id.startswith(f'{formatted_roomid}_{sender}_')]   

        if same_room_sender_runs:
            print(f"[WATCHER] 发现来自相同room_id和sender的DAG正在运行或等待触发, run_id: {same_room_sender_runs}, 提前停止")
            for run in same_room_sender_runs:
                print(f"[WATCHER] 提前停止DAG, run_id: {run.run_id}, 状态: {run.state}")
                Variable.set(f'{run.run_id}_pre_stop', True, serialize_json=True)  # 使用Variable作为标识变量，提前停止正在运行的DAG
       
        # 触发新的DAG运行
        now = datetime.now(timezone.utc)
        # 添加随机毫秒延迟，避免同时触发导致的execution_date冲突
        execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)
        run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'
        print(f"[WATCHER] 触发AI聊天DAG，run_id: {run_id}")
        try:
            trigger_dag(
                dag_id='zacks_ai_agent',
                conf=message_data,
                run_id=run_id,
                execution_date=execution_date
            )
            print(f"[WATCHER] 成功触发AI聊天DAG，execution_date: {execution_date}")
        except Exception as e:
            print(f"[WATCHER] 触发DAG失败: {str(e)}")
            # 如果是因为execution_date冲突，可以重试一次
            execution_date = now + timedelta(seconds=1, microseconds=hash(msg_id) % 1000000)
            trigger_dag(
                dag_id='zacks_ai_agent',
                conf=message_data,
                run_id=run_id,
                execution_date=execution_date
            )
            print(f"[WATCHER] 重试触发AI聊天DAG成功，execution_date: {execution_date}")
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
