
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一些公共函数

Author: claude89757
Date: 2025-04-16
"""

from airflow.models.variable import Variable


def get_dify_base_url(wx_user_name: str, wx_user_id: str, is_group: bool) -> str:
    """
    获取Dify的URL和API key
    Args:
        wx_user_name: 微信用户名
        wx_user_id: 微信用户ID
        is_group: 是否是群聊
        
    Returns:
        str: Dify的URL和API key
    """
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
    return dify_base_url, dify_api_key
