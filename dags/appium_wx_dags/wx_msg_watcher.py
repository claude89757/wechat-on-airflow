#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Appium 自动化微信操作的流程
Author: claude89757
Date: 2025-04-22
"""
import re

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable

from utils.dify_sdk import DifyAgent
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
        msg_list = []
        for message in messages:
            msg_list.append(message['msg'])
        msg = "\n".join(msg_list)

        # AI 回复
        response_msg_list = handle_msg_by_ai("Zacks", contact_name, msg)

        send_wx_msg_by_appium(contact_name, response_msg_list)

    return recent_new_msg



def handle_msg_by_ai(wx_user_name, room_id: str, msg: str) -> list:
    """
    使用AI回复消息
    Args:
        wx_user_name (str): 微信用户名
        room_id (str): 房间ID(这里指会话的名称)
        msg (str): 消息内容
    Returns:
        list: AI回复内容列表
    """
    # 获取Dify的URL和API key
    dify_base_url = Variable.get("ZACKS_DIFY_BASE_URL")
    dify_api_key = Variable.get("ZACKS_DIFY_API_KEY")
    
    # 初始化DifyAgent
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_base_url)

    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{room_id}"
    conversation_id = dify_agent.get_conversation_id_for_room(dify_user_id, room_id)

    # 获取在线图片信息
    dify_files = []
    online_img_info = Variable.get(f"{wx_user_name}_{room_id}_online_img_info", default_var={}, deserialize_json=True)
    if online_img_info:
        dify_files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": online_img_info.get("id", "")
        })
    
    # 获取AI回复
    try:
        print(f"[WATCHER] 开始获取AI回复")
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=msg,
            user_id=dify_user_id,
            conversation_id=conversation_id,
            files=dify_files,
            inputs={}
        )
    except Exception as e:
        if "Variable #conversation.section# not found" in str(e):
            # 清理会话记录
            conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
            if room_id in conversation_infos:
                del conversation_infos[room_id]
                Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
            print(f"已清除用户 {dify_user_id} 在房间 {room_id} 的会话记录")
            
            # 重新请求
            print(f"[WATCHER] 重新请求AI回复")
            full_answer, metadata = dify_agent.create_chat_message_stream(
                query=msg,
                user_id=dify_user_id,
                conversation_id=None,  # 使用新的会话
                files=dify_files,
                inputs={}
            )
        else:
            raise
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")

    if not conversation_id:
        try:
            # 新会话，重命名会话
            conversation_id = metadata.get("conversation_id")
            dify_agent.rename_conversation(conversation_id, dify_user_id, f"{wx_user_name}_{room_id}")
        except Exception as e:
            print(f"[WATCHER] 重命名会话失败: {e}")

        # 保存会话ID
        conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        # 旧会话，不重命名
        pass
    
    response_msg_list = []
    for response_part in re.split(r'\\n\\n|\n\n', full_answer):
        response_part = response_part.replace('\\n', '\n')
        response_msg_list.append(response_part)

    return response_msg_list


# 定义 DAG
with DAG(
    dag_id='appium_wx_msg_watcher',
    default_args={
        'owner': 'claude89757',
        'retries': 1,
        'retry_delay': timedelta(seconds=5),
    },
    description='使用Appium SDK自动化微信操作',
    schedule=timedelta(seconds=30),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信'],
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
