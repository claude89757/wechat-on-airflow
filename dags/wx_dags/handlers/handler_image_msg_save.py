#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自发图片消息简化处理模块 - 仅下载和上传到COS
"""

# 标准库导入
import os

# 自定义库导入
from wx_dags.common.wx_tools import download_image_from_windows_server
from wx_dags.common.wx_tools import upload_image_to_cos


def handler_image_msg_save(**context):
    """
    简化版图片处理 - 只下载和上传到COS，不进行AI处理
    仅用于处理自己发送的图片消息
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    room_id = message_data.get('roomid')
    msg_id = message_data.get('id')
    extra = message_data.get('extra', '')
    source_ip = message_data.get('source_ip')

    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    wx_user_name = wx_account_info['name']
    wx_user_id = wx_account_info['wxid']

    try:
        # 下载图片
        print("[WATCHER] 处理自己发送的图片：开始下载")
        image_file_path = download_image_from_windows_server(source_ip, msg_id, extra=extra)
        print(f"[WATCHER] 下载图片成功: {image_file_path}")

        # 上传到COS存储
        cos_path = upload_image_to_cos(image_file_path, wx_user_name, wx_user_id, room_id, context)
        print(f"[WATCHER] 上传图片到COS成功: {cos_path}")

        # 将图片本地路径传递到xcom中
        context['task_instance'].xcom_push(key='image_local_path', value=image_file_path)
        context['task_instance'].xcom_push(key='image_cos_path', value=cos_path)
        
        # 清理本地文件
        try:
            os.remove(image_file_path)
            print(f"[WATCHER] 成功删除本地图片: {image_file_path}")
        except Exception as e:
            print(f"[WATCHER] 删除本地图片失败: {e}")
            
    except Exception as e:
        print(f"[WATCHER] 处理自己发送的图片失败: {e}")
        return False
        
    return True
