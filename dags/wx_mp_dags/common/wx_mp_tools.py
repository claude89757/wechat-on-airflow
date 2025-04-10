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

    """
    更新微信公众号账号信息
    
    Args:
        to_user_name: 公众号原始ID (ToUserName)
        account_info: 要更新的账号信息
        
    Returns:
        dict: 更新后的账号信息
    """
    # 获取当前已缓存的公众号账号列表
    mp_account_list = Variable.get("WX_MP_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    
    # 更新时间
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    account_info['update_time'] = current_time
    
    # 确保有gh_user_id字段
    if 'gh_user_id' not in account_info:
        account_info['gh_user_id'] = to_user_name
    
    # 查找是否已存在该公众号
    found = False
    for i, account in enumerate(mp_account_list):
        if to_user_name == account.get('gh_user_id', ''):
            # 更新现有账号信息
            mp_account_list[i] = account_info
            found = True
            break
    
    # 如果未找到，添加新账号
    if not found:
        # 设置创建时间
        if 'create_time' not in account_info:
            account_info['create_time'] = current_time
        mp_account_list.append(account_info)
    
    # 更新账号列表
    Variable.set("WX_MP_ACCOUNT_LIST", mp_account_list, serialize_json=True)
    
    print(f"更新公众号信息: {account_info}")
    return account_info