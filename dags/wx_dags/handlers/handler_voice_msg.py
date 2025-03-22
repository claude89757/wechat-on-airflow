#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音消息处理模块
"""

# 标准库导入
import os
import re
import time

# Airflow相关导入
from airflow.exceptions import AirflowException
from airflow.models.variable import Variable

# 自定义库导入
from utils.dify_sdk import DifyAgent
from utils.wechat_channl import send_wx_msg
from wx_dags.common.wx_tools import get_contact_name
from wx_dags.common.wx_tools import download_voice_from_windows_server


def handler_voice_msg(**context):
    """
    处理语音消息, 通过Dify的AI助手进行聊天, 并回复微信消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    room_id = message_data.get('roomid')
    
    message_data = context.get('dag_run').conf
    room_id = message_data.get('roomid')
    sender = message_data.get('sender')
    msg_id = message_data.get('id')
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_self = message_data.get('is_self', False)  # 是否自己发送的消息
    is_group = message_data.get('is_group', False)  # 是否群聊
    extra = message_data.get('extra', '')
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    wx_user_name = wx_account_info['name']
    wx_user_id = wx_account_info['wxid']

    # 1. 下载语音
    voice_file_path = download_voice_from_windows_server(source_ip, msg_id)

    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else None)

    # 初始化dify
    dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=Variable.get("DIFY_BASE_URL"))
    
    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{wx_user_id}_{room_name}_{sender}"
    conversation_id = dify_agent.get_conversation_id_for_room(dify_user_id, room_id)

    # 2. 语音转文字
    try:
        transcribed_text = dify_agent.audio_to_text(voice_file_path)
        print(f"[WATCHER] 语音转文字结果: {transcribed_text}")
        
        if not transcribed_text.strip():
            raise Exception("语音转文字结果为空")
    except Exception as e:
        print(f"[WATCHER] 语音转文字失败: {e}")
        # 如果语音转文字失败，使用默认文本
        transcribed_text = "您发送了一条语音消息，但我无法识别内容。请问您想表达什么？"
    # 将语音转文字结果传递到xcom中
    context['task_instance'].xcom_push(key='voice_to_text_result', value=transcribed_text)

    # 3. 删除本地语音
    try:
        os.remove(voice_file_path)
    except Exception as e:
        print(f"[WATCHER] 删除本地语音失败: {e}")
    
    # 4. 发送转写的文本到Dify
    response, metadata = dify_agent.create_chat_message_stream(
        query=transcribed_text,  # 使用转写的文本
        user_id=dify_user_id,
        conversation_id=conversation_id,
        inputs={}
    )
    print(f"response: {response}")
    print(f"metadata: {metadata}")
    
    # 处理会话ID相关逻辑
    if not conversation_id:
        print(f"[WATCHER] 会话ID不存在，创建新会话")
        # 新会话，重命名会话
        conversation_id = metadata.get("conversation_id")
        # 获取房间和发送者信息
        room_name = get_contact_name(source_ip, room_id, wx_user_name)
        dify_agent.rename_conversation(conversation_id, dify_user_id, room_name)

        # 保存会话ID
        conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        print(f"[WATCHER] 会话ID已存在: {conversation_id}")
    
    # 发送AI回复到微信
    for response_part in re.split(r'\\n\\n|\n\n', response):
        response_part = response_part.replace('\\n', '\n')
        send_wx_msg(wcf_ip=source_ip, message=response_part, receiver=room_id)

    # 将转写文本和回复保存到xcom中
    context['task_instance'].xcom_push(key='ai_reply_msg', value=response)
