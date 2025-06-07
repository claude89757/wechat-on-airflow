#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/01/20
@Author  : claude89757
@File    : proxy_manager.py
@Software: PyCharm
代理管理模块 - 管理成功代理的缓存
"""
import time
import datetime
from airflow.models import Variable
import random
import requests


def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)


def get_cached_successful_proxies():
    """获取缓存的成功代理列表"""
    try:
        cached_proxies = Variable.get("ISZ_SUCCESSFUL_PROXIES", deserialize_json=True, default_var=[])
        print_with_timestamp(f"获取到缓存的成功代理数量: {len(cached_proxies)}")
        return cached_proxies
    except Exception as e:
        print_with_timestamp(f"获取缓存代理失败: {e}")
        return []


def update_successful_proxies(successful_proxy_dict):
    """更新成功的代理到缓存中"""
    try:
        cached_proxies = get_cached_successful_proxies()
        
        # 如果代理已经在缓存中，先移除再添加到最前面
        cached_proxies = [p for p in cached_proxies if p != successful_proxy_dict]
        cached_proxies.insert(0, successful_proxy_dict)
        
        # 只保留最近成功的10个代理
        cached_proxies = cached_proxies[:10]
        
        Variable.set(
            key="ISZ_SUCCESSFUL_PROXIES",
            value=cached_proxies,
            description=f"I深圳成功代理缓存 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            serialize_json=True
        )
        print_with_timestamp(f"✅ 更新成功代理缓存，当前缓存数量: {len(cached_proxies)}")
    except Exception as e:
        print_with_timestamp(f"更新成功代理缓存失败: {e}")


def remove_failed_proxy(failed_proxy_dict):
    """从缓存中移除失败的代理"""
    try:
        cached_proxies = get_cached_successful_proxies()
        original_count = len(cached_proxies)
        
        # 移除失败的代理
        cached_proxies = [p for p in cached_proxies if p != failed_proxy_dict]
        
        if len(cached_proxies) < original_count:
            Variable.set(
                key="ISZ_SUCCESSFUL_PROXIES",
                value=cached_proxies,
                description=f"I深圳成功代理缓存 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                serialize_json=True
            )
            print_with_timestamp(f"❌ 从缓存中移除失败代理，剩余缓存数量: {len(cached_proxies)}")
        
    except Exception as e:
        print_with_timestamp(f"移除失败代理缓存失败: {e}")


def get_proxy_list():
    """获取代理列表 - 优先使用缓存的成功代理"""
    try:
        # 首先获取缓存的成功代理
        cached_proxies = get_cached_successful_proxies()
        
        # 获取系统代理
        system_proxy = Variable.get("PROXY_URL", default_var="")
        if system_proxy:
            system_proxy_dict = {"https": system_proxy}
            print_with_timestamp(f"使用系统代理: {system_proxy}")
        else:
            system_proxy_dict = None
            print_with_timestamp("未配置系统代理")

        # 获取新的代理列表
        url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/isz_https_proxies.txt"
        print_with_timestamp(f"正在获取代理列表: {url}")
        
        proxies_for_request = system_proxy_dict if system_proxy_dict else None
        response = requests.get(url, proxies=proxies_for_request, timeout=30)
        
        if response.status_code != 200:
            print_with_timestamp(f"获取代理列表失败，状态码: {response.status_code}")
            new_proxy_list = []
        else:
            text = response.text.strip()
            if not text:
                print_with_timestamp("代理列表为空")
                new_proxy_list = []
            else:
                # 处理代理格式，确保格式正确
                proxy_lines = [line.strip() for line in text.split("\n") if line.strip() and ":" in line.strip()]
                new_proxy_list = []
                
                for line in proxy_lines:
                    try:
                        # 验证代理格式 ip:port
                        parts = line.split(":")
                        if len(parts) == 2 and parts[0] and parts[1].isdigit():
                            proxy_dict = {"https": f"http://{line}"}
                            new_proxy_list.append(proxy_dict)
                    except Exception as e:
                        print_with_timestamp(f"跳过无效代理格式: {line}, 错误: {e}")
                        continue
                
                random.shuffle(new_proxy_list)
                print_with_timestamp(f"成功加载 {len(new_proxy_list)} 个新代理")

        # 合并代理列表：优先使用缓存的成功代理，然后是新代理
        final_proxy_list = []
        
        # 添加缓存的成功代理（去重）
        if cached_proxies:
            final_proxy_list.extend(cached_proxies)
            print_with_timestamp(f"添加 {len(cached_proxies)} 个缓存的成功代理")
        
        # 添加新代理（排除已经在缓存中的）
        for new_proxy in new_proxy_list:
            if new_proxy not in final_proxy_list:
                final_proxy_list.append(new_proxy)
        
        # 如果没有可用代理，返回空列表
        if not final_proxy_list:
            print_with_timestamp("❌ 错误: 没有可用代理，无法进行请求")
            return []
            
        print_with_timestamp(f"代理列表准备完成，总计 {len(final_proxy_list)} 个代理（缓存: {len(cached_proxies)}, 新代理: {len(final_proxy_list) - len(cached_proxies)}）")
        return final_proxy_list
        
    except Exception as e:
        print_with_timestamp(f"获取代理列表失败: {e}")
        print_with_timestamp("❌ 错误: 无法获取代理，无法进行请求")
        return [] 