#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文本消息处理模块
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
from utils.wechat_channl import send_wx_image
from wx_dags.common.wx_tools import get_contact_name


def should_pre_stop(current_message, wx_user_name):
    """
    检查是否需要提前停止流程
    
    Args:
        current_message (dict): 当前处理的消息数据
        wx_user_name (str): 微信用户名称
        
    Raises:
        AirflowException: 如果需要提前停止流程则抛出异常
    """
    # 缓存的消息
    room_id = current_message.get('roomid')
    room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
    if current_message['id'] != room_msg_list[-1]['id']:
        print(f"[PRE_STOP] 最新消息id不一致，停止流程执行")
        raise AirflowException("检测到提前停止信号，停止流程执行")
    else:
        print(f"[PRE_STOP] 最新消息id一致，继续执行")


def handler_text_msg(**context):
    """
    处理文本类消息, 通过Dify的AI助手进行聊天, 并回复微信消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    room_id = message_data.get('roomid')
    sender = message_data.get('sender')
    msg_id = message_data.get('id')
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_self = message_data.get('is_self', False)  # 是否自己发送的消息
    is_group = message_data.get('is_group', False)  # 是否群聊
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    wx_user_name = wx_account_info['name']
    wx_user_id = wx_account_info['wxid']

    # 等待3秒，聚合消息
    time.sleep(5) 

    # 检查是否需要提前停止流程 
    should_pre_stop(message_data, wx_user_name)

    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else None)

    # 打印调试信息
    print(f"房间信息: {room_id}({room_name}), 发送者: {sender}({sender_name})")

    # 初始化dify
    dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=Variable.get("DIFY_BASE_URL"))

    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{wx_user_id}_{room_name}_{sender}"
    conversation_id = dify_agent.get_conversation_id_for_room(dify_user_id, room_id)

    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    # 如果开启AI，则遍历近期的消息是否已回复，没有回复，则合并到这次提问
    room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
    up_for_reply_msg_content_list = []
    up_for_reply_msg_id_list = []
    for msg in room_msg_list[-10:]:  # 只取最近的10条消息
        if not msg.get('is_reply'):
            up_for_reply_msg_content_list.append(msg.get('content', ''))
            up_for_reply_msg_id_list.append(msg['id'])
        else:
            pass
    # 整合未回复的消息
    question = "\n\n".join(up_for_reply_msg_content_list)

    print("-"*50)
    print(f"question: {question}")
    print("-"*50)
    
    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    dify_files = []
    # 获取在线图片信息
    online_img_info = Variable.get(f"{wx_user_name}_{room_id}_online_img_info", default_var={}, deserialize_json=True)
    if online_img_info:
        dify_files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": online_img_info.get("id", "")
        })

    dify_inputs = {}
    # 获取UI输入提示
    ui_input_prompt = Variable.get(f"{wx_user_name}_{wx_user_id}_ui_input_prompt")
    if ui_input_prompt:
        dify_inputs["ui_input_prompt"] = ui_input_prompt
    
     # 获取AI回复
    full_answer, metadata = dify_agent.create_chat_message_stream(
        query=question,
        user_id=dify_user_id,
        conversation_id=conversation_id,
        inputs=dify_inputs,
        files=dify_files
    )
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    response = full_answer

    if not conversation_id:
        # 新会话，重命名会话
        conversation_id = metadata.get("conversation_id")
        dify_agent.rename_conversation(conversation_id, dify_user_id, room_name)

        # 保存会话ID
        conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        # 旧会话，不重命名
        pass
    
    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_name)

    # 判断是否转人工
    if response.strip().lower() == '#转人工#':
        # 转人工
        print(f"[WATCHER] 转人工: {response}")
        human_room_ids = Variable.get(f"{wx_user_name}_{wx_user_id}_human_room_ids", default_var=[], deserialize_json=True)
        human_room_ids.append(room_id)
        Variable.set(f"{wx_user_name}_{wx_user_id}_human_room_ids", human_room_ids, serialize_json=True)
        return
    
    # 开启AI，且不是自己发送的消息，则自动回复消息
    dify_msg_id = metadata.get("message_id")
    try:
        for response_part in re.split(r'\\n\\n|\n\n', response):
            response_part = response_part.replace('\\n', '\n')
            if response_part.strip().endswith('.png'):
                # 发送图片 TODO(claude89757): 发送图片
                image_file_path = f"C:/Users/Administrator/Desktop/files/{response_part.strip()}"
                send_wx_image(wcf_ip=source_ip, image_path=image_file_path, receiver=room_id)
            elif response_part.strip().endswith('.mp4'):
                # 发送视频 TODO(claude89757): 发送视频
                image_file_path = f"C:/Users/Administrator/Desktop/files/{response_part.strip()}"
                send_wx_image(wcf_ip=source_ip, image_path=image_file_path, receiver=room_id)
            else:
                # 发送文本
                send_wx_msg(wcf_ip=source_ip, message=response_part, receiver=room_id)
        # 记录消息已被成功回复
        dify_agent.create_message_feedback(message_id=dify_msg_id, user_id=dify_user_id, rating="like", content="微信自动回复成功")

        # 缓存的消息中，标记消息已回复
        room_msg_list = Variable.get(f'{wx_user_name}_{room_id}_msg_list', default_var=[], deserialize_json=True)
        for msg in room_msg_list:
            if msg['id'] in up_for_reply_msg_id_list:
                msg['is_reply'] = True
        Variable.set(f'{wx_user_name}_{room_id}_msg_list', room_msg_list, serialize_json=True)

        # 删除缓存的在线图片信息
        try:
            Variable.delete(f"{wx_user_name}_{room_id}_online_img_info")
        except Exception as e:
            print(f"[WATCHER] 删除缓存的在线图片信息失败: {e}")

        # response缓存到xcom中
        context['task_instance'].xcom_push(key='ai_reply_msg', value=response)

    except Exception as error:
        print(f"[WATCHER] 发送消息失败: {error}")
        # 记录消息已被成功回复
        dify_agent.create_message_feedback(message_id=dify_msg_id, user_id=dify_user_id, rating="dislike", content=f"微信自动回复失败, {error}")

    # 打印会话消息
    messages = dify_agent.get_conversation_messages(conversation_id, dify_user_id)
    print("-"*50)
    for msg in messages:
        print(msg)
    print("-"*50)
