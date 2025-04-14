#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号图片消息处理模块
"""

# 标准库导入
import os

from wx_mp_dags.common.wx_mp_tools import upload_mp_image_to_cos


def save_mp_image_msg(**context):
    """
    处理微信公众号图片消息, 上传到COS存储
    
    处理流程:
    1. 接收用户发送的图片消息
    2. 下载图片文件并保存到临时目录
    3. 上传图片到COS存储
    4. 保存图片信息到数据库
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    to_user_name = message_data.get('ToUserName')  # 公众号原始ID
    from_user_name = message_data.get('FromUserName')  # 发送者的OpenID
    media_id = message_data.get('MediaId')  # 图片消息媒体id
    msg_id = message_data.get('MsgId')  # 消息ID
    pic_url = message_data.get('PicUrl')  # 图片链接

    # 获取公众号账号信息
    wx_mp_account_info = context.get('task_instance').xcom_pull(key='wx_mp_account_info')
    mp_name = wx_mp_account_info.get('name', to_user_name)

    try:
        # 1. 下载图片文件
        from wx_mp_dags.wx_mp_msg_watcher import download_image_from_wechat_mp
        access_token = context['task_instance'].xcom_pull(key='wx_mp_access_token')
        
        # 创建临时文件路径
        import tempfile
        temp_dir = tempfile.gettempdir()
        image_file_path = os.path.join(temp_dir, f"wx_mp_image_{from_user_name}_{msg_id}.jpg")
        
        # 下载图片
        saved_path = download_image_from_wechat_mp(access_token, media_id, image_file_path)
        if not saved_path:
            raise Exception("下载图片失败")
        
        print(f"[WATCHER] 图片已保存到: {saved_path}")

        # 2. 上传图片到COS存储
        cos_path = upload_mp_image_to_cos(
            image_file_path=saved_path,
            mp_name=mp_name,
            to_user_name=to_user_name,
            from_user_name=from_user_name,
            context=context
        )
        print(f"[WATCHER] 图片已上传到COS: {cos_path}")

        # 3. 将图片信息传递到xcom中
        context['task_instance'].xcom_push(key='mp_image_cos_path', value=cos_path)

    except Exception as e:
        print(f"[WATCHER] 保存微信公众号图片信息失败: {e}")
        raise

    # 清理临时文件
    try:
        if saved_path and os.path.exists(saved_path):
            os.remove(saved_path)
            print(f"[WATCHER] 临时图片文件已删除: {saved_path}")
    except Exception as e:
        print(f"[WATCHER] 删除临时文件失败: {e}")