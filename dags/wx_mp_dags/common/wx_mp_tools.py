#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号工具模块
提供微信公众号相关的工具函数,包括:
- 公众号信息获取和缓存
- 用户信息管理
- 消息处理等

Author: YuChanGongzhu
Date: 2025-04-10
"""

# 标准库导入
from datetime import datetime

# Airflow相关导入
from airflow.models import Variable
from utils.tecent_cos import upload_file

def get_mp_account_info(to_user_name: str) -> dict:
    """
    根据ToUserName获取微信公众号账号信息
    
    Args:
        to_user_name: 公众号原始ID (ToUserName)
        
    Returns:
        dict: 公众号账号信息，如果未找到则返回空字典
    """
    # 获取当前已缓存的公众号账号列表
    mp_account_list = Variable.get("WX_MP_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    
    # 遍历账号列表，查找匹配的公众号
    for account in mp_account_list:
        if to_user_name == account.get('gh_user_id', ''):
            print(f"获取到缓存的公众号信息: {account}")
            return account
    
    # 如果未找到匹配的公众号，返回包含基本信息的字典
    default_account = {
        'gh_user_id': to_user_name,
        'name': to_user_name,  # 默认使用原始ID作为名称
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    print(f"未找到匹配的公众号信息，使用默认值: {default_account}")
    return default_account


def upload_mp_image_to_cos(image_file_path: str, mp_name: str, to_user_name: str, from_user_name: str, context=None):
    """
    上传微信公众号图片到COS存储
    
    Args:
        image_file_path: 本地图片路径
        mp_name: 公众号名称
        to_user_name: 接收者ID (ToUserName)
        from_user_name: 发送者ID (FromUserName)
        context: Airflow上下文，用于xcom_push
        
    Returns:
        str: COS路径
    """
    # 构建COS存储路径
    cos_path = f"{mp_name}_{to_user_name}/{from_user_name}/{os.path.basename(image_file_path)}"
    try:

        # 使用特定的 bucket wx-mp-records-1347723456
        upload_response = upload_file(image_file_path, cos_path, bucket='wx-mp-records-1347723456')
        print(f"上传微信公众号图片到COS成功: {cos_path}")
        # 保存COS路径到xcom中，方便后续使用
        if context and 'task_instance' in context:
            context['task_instance'].xcom_push(key='mp_image_cos_path', value=cos_path)
        return cos_path
    except Exception as e:
        print(f"上传微信公众号图片到COS失败: {str(e)}")
        # 即使COS上传失败，也返回构建的路径
        return cos_path