#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025-01-28
@Author  : claude89757
@File    : get_isz_proxies_list.py
@Description : ISZ代理获取和验证模块，整合ydmap的代理逻辑
"""

import requests
import random
import threading
import concurrent.futures
import time
from utils.new_request import make_request


def is_valid_proxy(proxy):
    """简单的 IP 格式验证"""
    parts = proxy.split(':')
    if len(parts) != 2:
        return False
    ip, port = parts
    return ip.count('.') == 3 and port.isdigit()


def generate_proxies():
    """
    获取待检查的代理列表（完全参考ydmap_https_proxy_watcher.py）
    """
    urls = [
        "https://github.com/roosterkid/openproxylist/raw/main/HTTPS_RAW.txt",
        "https://raw.githubusercontent.com/yoannchb-pro/https-proxies/main/proxies.txt",
        "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/https.txt",
        "https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt",
    ]
    proxies = []
    proxy_url_infos = {}
    
    print("开始获取代理列表...")
    for url in urls:
        try:
            response = make_request('get', url)
            text = response.text.strip()
            lines = text.split("\n")
            lines = [line.strip() for line in lines if is_valid_proxy(line)]
            proxies.extend(lines)
            for line in lines:
                proxy_url_infos[line] = url
        except Exception as e:
            print(f"从 {url} 获取代理失败: {str(e)}")
            
    print(f"总计获取到 {len(proxies)} 个待检查代理")
    random.shuffle(proxies)
    return proxies, proxy_url_infos


def check_proxy_for_isz(proxy_url):
    """
    使用 requests 检查代理是否可用于ISZ（参考ydmap_https_proxy_watcher.py的check_proxy函数）
    proxy_url格式: "ip:port"
    """
    try:
        target_url = 'https://isz.ydmap.cn/srv100352/api/pub/sport/venue/getVenueOrderList?salesItemId=100341&curDate=1748188800000&venueGroupId=&t=1748187760876&md5__1182=n4%2BxnDR70%3DK7wqWqY5DsD7fmKD54sO2g8S4rTD'
        
        headers = {
            'Host': 'isz.ydmap.cn',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36',
            'accept': 'application/json, text/plain, */*',
            'timestamp': '1748187760918',
            'signature': 'xxxxxx',
            'visitor-id': 'xxxxxx',
            'x-requested-with': 'XMLHttpRequest'
        }
        
        # 完全参考ydmap的做法：从ip:port构造代理字典
        proxies = {
            'http': f'http://{proxy_url}',
            'https': f'http://{proxy_url}'
        }
        
        response = requests.get(
            target_url,
            headers=headers,
            proxies=proxies,
            timeout=3,
            verify=False
        )
        
        response_text = response.text
        
        # 判断返回内容是否包含"签名错误"，表示代理IP可用
        if (("签名错误" in response_text and "接口未签名" in response_text) or 
            ("访问验证" in response_text)):
            print(f"[{proxy_url}] 发现可用代理, 返回内容: {response_text[:100]}")
            return True
            
    except Exception as e:
        pass
    return False


def get_available_proxies_for_isz(max_workers=20):
    """
    获取可用的ISZ代理列表（完全参考ydmap_https_proxy_watcher.py的并发验证逻辑）
    返回格式: [{"https": "http://ip:port", "http": "http://ip:port"}, ...]
    """
    print("======开始获取ISZ可用代理列表======")
    
    # 获取代理列表
    proxies, proxy_url_infos = generate_proxies()
    print(f"开始检查 {len(proxies)} 个代理...")
    
    available_proxies = []
    max_workers = min(max_workers, len(proxies))
    
    def check_and_process(proxy):
        if check_proxy_for_isz(proxy):
            with threading.Lock():  # 使用锁防止并发写入问题
                # 构造标准的代理配置字典
                proxy_config = {
                    'http': f'http://{proxy}',
                    'https': f'http://{proxy}'
                }
                available_proxies.append(proxy_config)
                print(f"✅ 当前可用代理数量: {len(available_proxies)}")
    
    # 使用线程池并发检查代理（完全参考ydmap的做法）
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(check_and_process, proxy) for proxy in proxies]
        
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"代理检查过程中出现异常: {e}")
    
    print(f"======代理验证完成，共发现 {len(available_proxies)} 个可用代理======")
    
    if available_proxies:
        print(f"可用代理示例: {available_proxies[0]}")
    
    return available_proxies


def get_proxy_list_for_isz():
    """
    ISZ专用的代理获取函数
    返回可用的代理列表，格式兼容现有代码
    """
    try:
        available_proxies = get_available_proxies_for_isz()
        
        if not available_proxies:
            print("❌ 没有找到可用代理")
            return []
        
        print(f"✅ 成功获取 {len(available_proxies)} 个可用代理")
        return available_proxies
        
    except Exception as e:
        print(f"获取代理列表失败: {e}")
        return []


if __name__ == "__main__":
    # 测试代理获取功能
    print("开始测试ISZ代理获取功能...")
    proxy_list = get_proxy_list_for_isz()
    print(f"最终获取到的代理数量: {len(proxy_list)}")
    if proxy_list:
        print(f"代理列表示例: {proxy_list[:3]}")
