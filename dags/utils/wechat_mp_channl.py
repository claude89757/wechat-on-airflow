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

    def get_user_info(self, openid):
        """获取用户基本信息（包括UnionID机制）
        
        参数:
            openid: 普通用户的标识，对当前公众号唯一
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
        
        url = f"https://api.weixin.qq.com/cgi-bin/user/info?access_token={self.access_token}&openid={openid}"
        print(f"获取用户信息的 URL: {url}")
        
        response = requests.get(url)
        result = response.json()
        print(f"获取用户信息的结果: {result}")  
        
        if 'errcode' in result:
            raise Exception(f"获取用户信息失败: {result.get('errmsg', '未知错误')}")
        
        return result

    def get_followers(self, next_openid=None):
        """获取公众号关注者列表
        
        当关注者数量超过10000时，可通过填写next_openid参数，多次拉取列表的方式来获取完整关注者列表。
        每次调用最多拉取10000个关注者的OpenID。
        
        参数:
            next_openid: 第一个拉取的OPENID，不填默认从头开始拉取
            
        返回:
            包含以下字段的字典:
            - total: 关注该公众账号的总用户数
            - count: 拉取的OPENID个数，最大值为10000
            - data: 列表数据，包含openid字段
            - next_openid: 拉取列表的最后一个用户的OPENID，为空则表示已拉取完毕
        
        使用示例:
            # 首次调用，获取前10000个关注者
            result = mp_bot.get_followers()
            all_openids = result['data']['openid']
            
            # 如果next_openid不为空，继续获取下一批关注者
            next_openid = result['next_openid']
            while next_openid:
                result = mp_bot.get_followers(next_openid)
                all_openids.extend(result['data']['openid'])
                next_openid = result['next_openid']
        """
        if not self.access_token:
            self.get_access_token()
        
        url = f"https://api.weixin.qq.com/cgi-bin/user/get?access_token={self.access_token}"
        if next_openid:
            url += f"&next_openid={next_openid}"
        
        print(f"获取关注者列表的 URL: {url}")
        
        response = requests.get(url)
        result = response.json()
        
        if 'errcode' in result:
            raise Exception(f"获取关注者列表失败: {result.get('errmsg', '未知错误')}")
        
        return result

    def get_all_followers(self):
        """获取公众号全部关注者列表
        
        自动处理分页逻辑，一次性返回所有关注者的OpenID列表，无需手动处理next_openid。
        内部会自动多次调用get_followers方法，直到获取所有关注者。
        
        返回:
            dict: 包含以下字段的字典:
            - total: 关注该公众账号的总用户数
            - openid_list: 所有关注者的OpenID列表
        """
        # 首次调用，获取第一批关注者
        result = self.get_followers()
        total = result.get('total', 0)
        
        # 初始化存储所有openid的列表
        all_openids = []
        if 'data' in result and 'openid' in result['data']:
            all_openids.extend(result['data'])
        
        # 如果next_openid不为空，继续获取下一批关注者
        next_openid = result.get('next_openid')
        while next_openid:
            print(f"继续获取下一批关注者，next_openid: {next_openid}")
            result = self.get_followers(next_openid)
            if 'data' in result and 'openid' in result['data']:
                all_openids.extend(result['data'])
            next_openid = result.get('next_openid')
            
            # 如果next_openid为空或者与上一次相同，说明已经获取完毕
            if not next_openid or next_openid == result.get('next_openid'):
                break
        
        return {
            'total': total,
            'openid_list': all_openids
        }
