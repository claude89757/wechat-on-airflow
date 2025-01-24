#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import re
import random
import time
from datetime import datetime, timedelta
from threading import Thread

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException

# 自定义库导入
from utils.wechat_channl import send_wx_msg
from utils.wechat_channl import get_wx_contact_list
from utils.wechat_channl import get_wx_room_members
from utils.llm_channl import get_llm_response


DAG_ID = "broadcast_agent_001"


def check_message_is_legal(content):
    """
    使用大模型检查消息是否合规
    """
    system_prompt = "你是一个专业的内容审核助手。请严格审核以下内容是否包含违规信息（包括但不限于：违法犯罪、暴力血腥、色情低俗、政治敏感、人身攻击、歧视言论等）。如发现任何违规内容，直接返回'不合规'，否则返回'合格'。无需解释理由。"
    user_question = content
    print(f"raw_message: {user_question}")
    response = get_llm_response(user_question, model_name="gpt-4o-mini", system_prompt=system_prompt)
    print(f"check_message_is_legal: {response}")
    if "不合规" in response:
        return False
    return True


def chat_with_dify_agent(**context):
    """
    通过Dify的AI助手进行聊天，并回复微信消息
    """
    # 当前消息
    current_message_data = context.get('dag_run').conf["current_message"]
    # 获取消息数据 
    sender = current_message_data.get('sender', '')  # 发送者ID
    room_id = current_message_data.get('roomid', '')  # 群聊ID
    msg_id = current_message_data.get('id', '')  # 消息ID
    content = current_message_data.get('content', '')  # 消息内容
    source_ip = current_message_data.get('source_ip', '')  # 获取源IP, 用于发送消息
    is_group = current_message_data.get('is_group', False)  # 是否群聊

    # 获取群名称
    wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
    print(f"wx_contact_list: {len(wx_contact_list)}")
    contact_infos = {}
    for contact in wx_contact_list:
        wxid = contact.get('wxid', '')
        contact_infos[wxid] = contact

    # 获取sender的nickname
    room_members = get_wx_room_members(wcf_ip=source_ip, room_id=room_id)
    print(f"room_members: {len(room_members)}")
    room_members_infos = {}
    for member in room_members:
        print(f"member: {member}")
        wxid = member.get('wxid', '')
        room_members_infos[wxid] = member



    # 获取sender的nickname
    source_sender_nickname = room_members_infos.get(sender, {}).get('name', '')
    source_room_name = contact_infos.get(room_id, {}).get('name', '')

    # 构造消息  
    msg = f"[ {source_sender_nickname} from {source_room_name} ] 💬\n{content}"

    # 检查消息是否合规
    if not check_message_is_legal(msg):
        print(f"[WARNING] 消息不合规, 停止处理")
        return
    
    # 广播消息
    supper_big_rood_ids = Variable.get('supper_big_rood_ids', default_var=[], deserialize_json=True)
    for tem_room_id in supper_big_rood_ids:
        if tem_room_id == room_id:
            # 源群不发送
            pass
        else:
            send_wx_msg(wcf_ip=source_ip, message=msg, receiver=tem_room_id)
            # 随机等待0-2秒
            wait_time = random.uniform(0, 2)
            time.sleep(wait_time)
            


# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 0,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=10,
    catchup=False,
    tags=['基于Dify的AI助手'],
    description='基于Dify的AI助手',
)


process_ai_chat_task = PythonOperator(
    task_id='process_ai_chat',
    python_callable=chat_with_dify_agent,
    provide_context=True,
    dag=dag,
)

process_ai_chat_task
