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

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.api.common.trigger_dag import trigger_dag

# 自定义库导入
from wx_dags.common.wx_tools import WX_MSG_TYPES
from wx_dags.common.wx_tools import update_wx_user_info
from wx_dags.common.wx_tools import check_ai_enable
from utils.redis import RedisHandler

# 导入消息处理器
from wx_dags.handlers.handler_text_msg import handler_text_msg
from wx_dags.handlers.handler_image_msg import handler_image_msg
from wx_dags.handlers.handler_voice_msg import handler_voice_msg
from wx_dags.handlers.handler_video_msg_for_ai_tennis import handler_video_msg


DAG_ID = "zacks_wx_msg_watcher"


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
    message_data['id'] = int(message_data['id'])
    print("[WATCHER] 收到微信消息:")
    print("[WATCHER] 消息类型:", message_data.get('type'))
    print("[WATCHER] 消息内容:", message_data.get('content'))
    print("[WATCHER] 发送者:", message_data.get('sender'))
    print("[WATCHER] ROOM:", message_data.get('roomid'))
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
    is_self = message_data.get('is_self', False)  # 是否自己发送的消息
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 获取用户信息, 并缓存
    wx_account_info = update_wx_user_info(source_ip)
    wx_user_name = wx_account_info['name']
    wx_user_id = wx_account_info['wxid']
    # 将微信账号信息传递到xcom中供后续任务使用
    context['task_instance'].xcom_push(key='wx_account_info', value=wx_account_info)

    try:
        # 账号的消息计时器+1
        msg_count = Variable.get(f"{wx_user_name}_msg_count", default_var=0, deserialize_json=True)
        Variable.set(f"{wx_user_name}_msg_count", msg_count+1, serialize_json=True)
    except Exception as error:
        # 不影响主流程
        print(f"[WATCHER] 更新消息计时器失败: {error}")

    # 分场景分发微信消息
    next_task_list = []
    if is_self:
        print("[WATCHER] 自己发送的消息，不处理")
        return
    elif WX_MSG_TYPES.get(msg_type) == "文字":

        # 使用Redis缓存消息
        redis_handler = RedisHandler()
        redis_handler.append_msg_list(f'{wx_user_id}_{room_id}_msg_list', message_data) # 只缓存最近的100条消息

        # 决策下游的任务
        if not is_group:
            next_task_list.append('handler_text_msg')
        else:
            # 群聊消息
            if room_id in ["XXXX"]:
                # 开白的群里
                next_task_list.append('handler_text_msg')
            else:
                pass
    
    elif WX_MSG_TYPES.get(msg_type) == "语音":
        # 语音消息
        if not is_group:
            next_task_list.append('handler_voice_msg')
        else:
            pass
    elif WX_MSG_TYPES.get(msg_type) == "视频":
        # 视频消息
        # 开白的群里
        next_task_list.append('handler_video_msg')
    elif WX_MSG_TYPES.get(msg_type) == "图片":
        if not is_group:
            # 图片消息
            next_task_list.append('handler_image_msg')
        else:
            # 群聊图片消息
            pass    
    else:
        # 其他类型消息暂不处理
        print("[WATCHER] 不触发AI聊天流程")
 
    return next_task_list


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['个人微信'],
    description='个人微信消息监控',
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

# 创建处理图片消息的任务
handler_image_msg_task = PythonOperator(
    task_id='handler_image_msg',
    python_callable=handler_image_msg,
    provide_context=True,
    dag=dag)

# 创建处理语音消息的任务
handler_voice_msg_task = PythonOperator(
    task_id='handler_voice_msg',
    python_callable=handler_voice_msg,
    provide_context=True,
    dag=dag
)

# 创建处理视频消息的任务
handler_video_msg_task = PythonOperator(
    task_id='handler_video_msg',
    python_callable=handler_video_msg,
    provide_context=True,
    dag=dag
)
# 设置任务依赖关系
process_message_task >> [handler_text_msg_task, handler_image_msg_task, handler_voice_msg_task, handler_video_msg_task]
