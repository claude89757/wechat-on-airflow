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
from utils.redis import RedisHandler
from wx_dags.common.wx_tools import get_contact_name


def should_pre_stop(current_message, wx_user_id, room_id):
    """
    检查是否需要提前停止流程
    
    Args:
        current_message (dict): 当前处理的消息数据
        wx_user_name (str): 微信用户名称
        
    Raises:
        AirflowException: 如果需要提前停止流程则抛出异常
    """   
    # 使用Redis缓存消息
    redis_handler = RedisHandler()
    room_msg_list = redis_handler.get_msg_list(f'{wx_user_id}_{room_id}_msg_list')

    if room_msg_list and current_message['id'] != room_msg_list[-1]['id']:
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
    print(f"[TEXT_MSG] 接收到消息-------是不是群聊: {is_group}")

    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    wx_user_name = wx_account_info['name']
    wx_user_id = wx_account_info['wxid']

    # 等待3秒，聚合消息
    time.sleep(3) 

    # 检查是否需要提前停止流程 
    should_pre_stop(message_data, wx_user_id, room_id)

    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else None)

    # 打印调试信息
    print(f"房间信息: {room_id}({room_name}), 发送者: {sender}({sender_name})")

    # 获取Dify的URL和API key
    dify_base_url = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_base_url", default_var="")
    if not dify_base_url:
        dify_base_url = Variable.get("DIFY_BASE_URL")
    if is_group:
        try:
            dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_group_dify_api_key")
        except:
            dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
    else:
        dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
    if not dify_api_key:
        dify_api_key = Variable.get("DIFY_API_KEY")

    print(f"dify_base_url: {dify_base_url}")
    print(f"dify_api_key: {dify_api_key}")
    
    # 初始化DifyAgent
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_base_url)

    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{wx_user_id}_{room_name}"
    conversation_id = dify_agent.get_conversation_id_for_room(dify_user_id, room_id)

    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_id, room_id)

    # 获取缓存的消息
    redis_handler = RedisHandler()
    room_msg_list = redis_handler.get_msg_list(f'{wx_user_id}_{room_id}_msg_list')
    up_for_reply_msg_content_list = []
    up_for_reply_msg_id_list = []
    for msg in room_msg_list[-5:]:  # 只取最近的5条消息
        up_for_reply_msg_content_list.append(msg.get('content', ''))
        up_for_reply_msg_id_list.append(msg['id'])

    # 整合未回复的消息
    question = "\n\n".join(up_for_reply_msg_content_list)

    print("-"*50)
    print(f"question: {question}")
    print("-"*50)
    
    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_id, room_id)

    # 获取在线图片信息
    dify_files = []
    online_img_info = Variable.get(f"{wx_user_name}_{room_id}_online_img_info", default_var={}, deserialize_json=True)
    if online_img_info:
        dify_files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": online_img_info.get("id", "")
        })
    
    # 群聊标识
    input_params = {"is_group": "true"} if is_group else {}

    # 获取AI回复
    try:
        print(f"[WATCHER] 开始获取AI回复---test")
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=question,
            user_id=dify_user_id,
            conversation_id=conversation_id,
            files=dify_files,
            inputs=input_params
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
            full_answer, metadata = dify_agent.create_chat_message_stream(
                query=question,
                user_id=dify_user_id,
                conversation_id=None,  # 使用新的会话
                files=dify_files,
                inputs=input_params
            )
        else:
            raise
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")
    response = full_answer
    context['task_instance'].xcom_push(key='token_usage_data', value=metadata)

    if not conversation_id:
        try:
            # 新会话，重命名会话
            conversation_id = metadata.get("conversation_id")
            dify_agent.rename_conversation(conversation_id, dify_user_id, room_name)
        except Exception as e:
            print(f"[WATCHER] 重命名会话失败: {e}")

        # 保存会话ID
        conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        # 旧会话，不重命名
        pass
    
    # 检查是否需要提前停止流程
    should_pre_stop(message_data, wx_user_id, room_id)

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
    
    # 开启AI，且不是自己发送的消息，则自动回复消息
    if response.strip():
        dify_msg_id = metadata.get("message_id")
        try:
            for response_part in re.split(r'\\n\\n|\n\n', response):
                response_part = response_part.replace('\\n', '\n')
                if response_part.strip().endswith('.png'):
                    # 发送图片
                    image_file_path = f"C:/Users/Administrator/Desktop/files/{response_part.strip()}"
                    send_wx_image(wcf_ip=source_ip, image_path=image_file_path, receiver=room_id)
                elif response_part.strip().endswith('.mp4'):
                    # 发送视频
                    image_file_path = f"C:/Users/Administrator/Desktop/files/{response_part.strip()}"
                    send_wx_image(wcf_ip=source_ip, image_path=image_file_path, receiver=room_id)
                else:
                    # 发送文本
                    send_wx_msg(wcf_ip=source_ip, message=response_part, receiver=room_id)
            
            # 删除缓存的消息
            redis_handler.delete_msg_key(f'{wx_user_id}_{room_id}_msg_list')

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
