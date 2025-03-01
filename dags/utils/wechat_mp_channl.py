#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
微信公众号机器人客户端

用于与微信公众号平台进行交互,实现消息收发等功能。

Author: by cursor
Date: 2025-02-27
"""

import requests
import json

class WeChatMPBot:
    def __init__(self, appid, appsecret):
        self.appid = appid
        self.appsecret = appsecret
        self.access_token = None
        self.token_expiry = 0

    def get_access_token(self):
        """获取稳定的 Access Token"""
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={self.appid}&secret={self.appsecret}"
        print(f"获取 Access Token 的 URL: {url}")
        response = requests.get(url)
        data = response.json()
        if 'access_token' in data:
            self.access_token = data['access_token']
            self.token_expiry = data['expires_in']
            return self.access_token
        else:
            raise Exception(f"获取 Access Token 失败: {data.get('errmsg', '未知错误')}")

    def send_text_message(self, to_user, content):
        """发送文本消息"""
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送文本消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送文本消息失败: {result.get('errmsg', '未知错误')}")

    def send_image_message(self, to_user, media_id):
        """发送图片消息"""
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送图片消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "image",
            "image": {
                "media_id": media_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送图片消息失败: {result.get('errmsg', '未知错误')}")

    def get_user_info(self, openid, lang="zh_CN"):
        """获取用户基本信息（包括UnionID机制）
        
        参数:
            openid: 普通用户的标识，对当前公众号唯一
            lang: 返回国家地区语言版本，zh_CN 简体，zh_TW 繁体，en 英语
            
        返回:
            用户信息的字典，包含以下字段:
            - subscribe: 用户是否订阅该公众号标识
            - openid: 用户的标识
            - language: 用户的语言
            - subscribe_time: 用户关注时间
            - unionid: 只有在用户将公众号绑定到微信开放平台帐号后，才会出现该字段
            - remark: 公众号运营者对粉丝的备注
            - groupid: 用户所在的分组ID
            - tagid_list: 用户被打上的标签ID列表
            - subscribe_scene: 用户关注的渠道来源
            - qr_scene: 二维码扫码场景
            - qr_scene_str: 二维码扫码场景描述
        """
        if not self.access_token:
            self.get_access_token()
        
        url = f"https://api.weixin.qq.com/cgi-bin/user/info?access_token={self.access_token}&openid={openid}&lang={lang}"
        print(f"获取用户信息的 URL: {url}")
        
        response = requests.get(url)
        result = response.json()
        
        if 'errcode' in result:
            raise Exception(f"获取用户信息失败: {result.get('errmsg', '未知错误')}")
        
        return result
