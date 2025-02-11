#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024-03-20 02:35:46
@Author  : claude89757
@File    : new_request.py
@Description : 统一的请求处理工具
"""

import requests
from airflow.models.variable import Variable


def make_request(method, url, use_proxy=True, **kwargs):
    """统一的请求处理函数
    
    Args:
        method: 请求方法 ('get' 或 'put')
        url: 请求URL
        use_proxy: 是否使用系统代理
        **kwargs: 传递给 requests 的其他参数
    """
    if use_proxy:
        system_proxy = Variable.get("PROXY_URL", default_var="")
        if system_proxy:
            kwargs['proxies'] = {"https": system_proxy}
    
    if method.lower() == 'get':
        return requests.get(url, **kwargs)
    elif method.lower() == 'put':
        return requests.put(url, **kwargs)
    elif method.lower() == 'delete':
        return requests.delete(url, **kwargs)
    elif method.lower() == 'post':
        return requests.post(url, **kwargs)
    else:
        raise ValueError(f"Unsupported method: {method}")
    