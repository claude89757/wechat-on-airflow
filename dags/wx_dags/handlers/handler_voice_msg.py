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
from utils.redis import RedisHandler
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
    # 如果是群聊，先检查是否有群聊专用的API key
    if is_group:
        try:
            dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_group_dify_api_key")
        except:
            dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
    else:
        dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
        
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=Variable.get("DIFY_BASE_URL"))
    
    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{wx_user_id}_{room_name}"
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
        print(f"[WATCHER] 获取到缓存的在线图片信息: {online_img_info}")

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
    
    # 如果开启AI，则遍历近期的消息是否已回复，没有回复，则合并到这次提问
    redis_handler = RedisHandler()
    room_msg_list = redis_handler.get_msg_list(f'{wx_user_id}_{room_id}_msg_list')
    up_for_reply_msg_content_list = []
    up_for_reply_msg_id_list = []
    for msg in room_msg_list[-5:]:  # 只取最近的5条消息
        up_for_reply_msg_content_list.append(msg.get('content', ''))
        up_for_reply_msg_id_list.append(msg['id'])
    # 整合未回复的消息
    all_messages = "\n\n".join(up_for_reply_msg_content_list)
    # 如果有缓存的消息，将当前语音转写的文本追加到最后
    if all_messages:
        query = all_messages + "\n\n" + transcribed_text
    else:
        query = transcribed_text
        
    # 4. 发送转写的文本到Dify
    response, metadata = dify_agent.create_chat_message_stream(
        query=query,  # 使用合并后的文本
        user_id=dify_user_id,
        conversation_id=conversation_id,
        files=dify_files if dify_files else None,
        inputs={}
    )
    print(f"response: {response}")
    print(f"metadata: {metadata}")
    context['task_instance'].xcom_push(key='token_usage_data', value=metadata)
    
    # 判断是否转人工
    if "#转人工#" in response.strip().lower():
        print(f"[WATCHER] 转人工: {response}")
        # 记录转人工的房间ID
        human_room_ids = Variable.get(f"{wx_user_name}_{wx_user_id}_human_room_ids", default_var=[], deserialize_json=True)
        human_room_ids.append(room_id)
        human_room_ids = list(set(human_room_ids))  # 去重
        Variable.set(f"{wx_user_name}_{wx_user_id}_human_room_ids", human_room_ids, serialize_json=True)
        
        # 删除缓存的消息
        redis_handler.delete_msg_key(f'{wx_user_id}_{room_id}_msg_list')
        # 删除标签
        response = response.replace("#转人工#", "")
    
    if "#沉默#" in response.strip().lower():
        # 删除缓存的消息
        redis_handler.delete_msg_key(f'{wx_user_id}_{room_id}_msg_list')
        # 删除标签
        response = response.replace("#沉默#", "")
    
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
    context['task_instance'].xcom_push(key='token_usage_data', value=metadata)
    
    # 删除缓存的在线图片信息
    try:
        if online_img_info:
            Variable.delete(f"{wx_user_name}_{room_id}_online_img_info")
            print(f"[WATCHER] 删除缓存的在线图片信息成功")
    except Exception as e:
        print(f"[WATCHER] 删除缓存的在线图片信息失败: {e}")
