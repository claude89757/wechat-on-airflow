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
from airflow.operators.python import ShortCircuitOperator, PythonOperator
from airflow.models import Variable

from utils.dify_sdk import DifyAgent
from utils.appium.wx_appium import get_recent_new_msg_by_appium
from utils.appium.wx_appium import send_wx_msg_by_appium


def monitor_chats(**context):
    """监控聊天消息"""
    print(f"[WATCHER] 监控聊天消息")
    task_index = int(context['task_instance'].task_id.split('_')[-1])
    try:
        appium_server_info = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)[task_index]
        print(f"[WATCHER] 获取Appium服务器信息: {appium_server_info}")
    except Exception as e:
        print(f"[WATCHER] 获取Appium服务器信息失败: {e}")
        return False

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']

    # 获取最近的新消息
    recent_new_msg = get_recent_new_msg_by_appium(appium_url, device_name, login_info)
    print(f"[WATCHER] 获取最近的新消息: {recent_new_msg}")
    
    # 缓存到XCOM
    context['ti'].xcom_push(key=f'recent_new_msg_{task_index}', value=recent_new_msg)

    # 如果最近的新消息不为空，则返回True
    if recent_new_msg:
        return True
    else:
        return False


def send_messages(**context):
    """发送消息"""
    print(f"[SENDER] 发送消息")
    task_index = int(context['task_instance'].task_id.split('_')[-1])
    appium_server_info = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)[task_index]
    print(f"[WATCHER] 获取Appium服务器信息: {appium_server_info}")

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']

    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key=f'recent_new_msg_{task_index}')
    print(f"[SENDER] 获取XCOM: {recent_new_msg}")
    
    # 发送消息
    for contact_name, messages in recent_new_msg.items():
        msg_list = []
        for message in messages:
            msg_list.append(message['msg'])
        msg = "\n".join(msg_list)

        # AI 回复
        response_msg_list = handle_msg_by_ai(dify_api_url, dify_api_key, wx_name, contact_name, msg)

        send_wx_msg_by_appium(appium_url, device_name, contact_name, response_msg_list)

    return recent_new_msg



def handle_msg_by_ai(dify_api_url, dify_api_key, wx_user_name, room_id, msg) -> list:
    """
    使用AI回复消息
    Args:
        wx_user_name (str): 微信用户名
        room_id (str): 房间ID(这里指会话的名称)
        msg (str): 消息内容
    Returns:
        list: AI回复内容列表
    """
    
    # 初始化DifyAgent
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_api_url)

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
    default_args={'owner': 'claude89757'},
    description='使用Appium SDK自动化微信操作',
    schedule=timedelta(seconds=60),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信'],
) as dag:

    # 监控聊天消息
    wx_watcher_0 = ShortCircuitOperator(task_id='wx_watcher_0', python_callable=monitor_chats)
    wx_watcher_1 = ShortCircuitOperator(task_id='wx_watcher_1', python_callable=monitor_chats)
    wx_watcher_2 = ShortCircuitOperator(task_id='wx_watcher_2', python_callable=monitor_chats)
    wx_watcher_3 = ShortCircuitOperator(task_id='wx_watcher_3', python_callable=monitor_chats)
    wx_watcher_4 = ShortCircuitOperator(task_id='wx_watcher_4', python_callable=monitor_chats)
    wx_watcher_5 = ShortCircuitOperator(task_id='wx_watcher_5', python_callable=monitor_chats)
    wx_watcher_6 = ShortCircuitOperator(task_id='wx_watcher_6', python_callable=monitor_chats)
    wx_watcher_7 = ShortCircuitOperator(task_id='wx_watcher_7', python_callable=monitor_chats)
    wx_watcher_8 = ShortCircuitOperator(task_id='wx_watcher_8', python_callable=monitor_chats)
    wx_watcher_9 = ShortCircuitOperator(task_id='wx_watcher_9', python_callable=monitor_chats)

    # 发送消息
    wx_sender_0 = PythonOperator(task_id='wx_sender_0', python_callable=send_messages)
    wx_sender_1 = PythonOperator(task_id='wx_sender_1', python_callable=send_messages)
    wx_sender_2 = PythonOperator(task_id='wx_sender_2', python_callable=send_messages)
    wx_sender_3 = PythonOperator(task_id='wx_sender_3', python_callable=send_messages)
    wx_sender_4 = PythonOperator(task_id='wx_sender_4', python_callable=send_messages)
    wx_sender_5 = PythonOperator(task_id='wx_sender_5', python_callable=send_messages)
    wx_sender_6 = PythonOperator(task_id='wx_sender_6', python_callable=send_messages)
    wx_sender_7 = PythonOperator(task_id='wx_sender_7', python_callable=send_messages)
    wx_sender_8 = PythonOperator(task_id='wx_sender_8', python_callable=send_messages)
    wx_sender_9 = PythonOperator(task_id='wx_sender_9', python_callable=send_messages)

    # 设置依赖关系
    wx_watcher_0 >> wx_sender_0
    wx_watcher_1 >> wx_sender_1
    wx_watcher_2 >> wx_sender_2
    wx_watcher_3 >> wx_sender_3
    wx_watcher_4 >> wx_sender_4
    wx_watcher_5 >> wx_sender_5
    wx_watcher_6 >> wx_sender_6
    wx_watcher_7 >> wx_sender_7
    wx_watcher_8 >> wx_sender_8
    wx_watcher_9 >> wx_sender_9
