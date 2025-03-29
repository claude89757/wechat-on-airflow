#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片消息处理模块
"""

# 标准库导入
import os

# Airflow相关导入
from airflow.models.variable import Variable

# 自定义库导入
from utils.dify_sdk import DifyAgent
from wx_dags.common.wx_tools import get_contact_name
from wx_dags.common.wx_tools import download_image_from_windows_server
from wx_dags.common.wx_tools import upload_image_to_cos


def handler_image_msg(**context):
    """
    处理图片消息, 通过Dify的AI助手进行聊天, 并回复微信消息
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
    extra = message_data.get('extra', '')
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')

    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    wx_user_name = wx_account_info['name']
    wx_user_id = wx_account_info['wxid']

    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else None)

    try:
        # 下载图片
        image_file_path = download_image_from_windows_server(source_ip, msg_id, extra=extra)
        print(f"[WATCHER] 下载图片成功: {image_file_path}")

        # 上传到COS存储
        cos_path = upload_image_to_cos(image_file_path, wx_user_name, wx_user_id, room_id, context)
        print(f"[WATCHER] 上传图片到COS成功: {cos_path}")

        # 将图片本地路径传递到xcom中
        context['task_instance'].xcom_push(key='image_cos_path', value=cos_path)

        # 上传图片到Dify
        dify_user_id = f"{wx_user_name}_{wx_user_id}_{room_name}"

        # 如果是群聊，先检查是否有群聊专用的API key
        if is_group:
            try:
                dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_group_dify_api_key")
            except:
                dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
        else:
            dify_api_key = Variable.get(f"{wx_user_name}_{wx_user_id}_dify_api_key")
            
        dify_agent = DifyAgent(api_key=dify_api_key, base_url=Variable.get("DIFY_BASE_URL"))
        online_img_info = dify_agent.upload_file(image_file_path, dify_user_id)
        print(f"[WATCHER] 上传图片到Dify成功: {online_img_info}")

        # 这里不发起聊天消息,缓存到Airflow的变量中,等待文字消息来触发
        Variable.set(f"{wx_user_name}_{room_id}_online_img_info", online_img_info, serialize_json=True)
    except Exception as e:
        print(f"[WATCHER] 保存在线图片信息失败: {e}")
        # 回复客户说网络不好，图片接受异常，口气要委婉
        # send_wx_msg(wcf_ip=source_ip, message="亲，网络有点问题，图片没收到，稍后再试试哦~", receiver=room_id)

    # TODO:删除本地图片
    try:
        os.remove(image_file_path)
    except Exception as e:
        print(f"[WATCHER] 删除本地图片失败: {e}")
