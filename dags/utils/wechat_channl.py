#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests


def send_wx_msg_by_wcf_api(wcf_ip: str, message: str, receiver: str, aters: str = "") -> bool:
    """
    通过WCF API发送微信消息
    Args:
        wcf_ip: WCF服务器IP
        message: 要发送的消息内容
        receiver: 接收者
        aters: 要@的用户，可选
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}"
    
    print(f"[WX] 发送消息 -> {receiver} {'@'+aters if aters else ''}")
    print(f"[WX] 内容: {message}")
    
    try:
        payload = {"msg": message, "receiver": receiver, "aters": aters}
        response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
        print(f"[WX] 响应: {response.status_code} - {response.text}")
        
        response.raise_for_status()
        
        result = response.json()
        if result.get('status') != 0:
            raise Exception(f"发送失败: {result.get('message', '未知错误')}")
        
        print("[WX] 发送成功")    
        return True
        
    except requests.exceptions.RequestException as e:
        error_msg = f"发送失败: {str(e)}"
        print(error_msg)
        raise Exception(error_msg)