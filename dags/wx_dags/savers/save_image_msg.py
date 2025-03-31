#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图片消息处理模块
"""

# 标准库导入
import os

from wx_dags.common.wx_tools import get_contact_name
from wx_dags.common.wx_tools import download_image_from_windows_server
from wx_dags.common.wx_tools import upload_image_to_cos


def save_image_msg(**context):
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

    try:
        # 下载图片
        image_file_path = download_image_from_windows_server(source_ip, msg_id, extra=extra)
        print(f"[WATCHER] 下载图片成功: {image_file_path}")

        # 上传到COS存储
        cos_path = upload_image_to_cos(image_file_path, wx_user_name, wx_user_id, room_id, context)

        # 将图片本地路径传递到xcom中
        context['task_instance'].xcom_push(key='image_cos_path', value=cos_path)

    except Exception as e:
        print(f"[WATCHER] 保存在线图片信息失败: {e}")

    # TODO:删除本地图
    try:
        os.remove(image_file_path)
    except Exception as e:
        print(f"[WATCHER] 删除本地图片失败: {e}")
