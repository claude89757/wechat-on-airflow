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
import os
from urllib.parse import urlparse
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

    def send_voice_message(self, to_user, media_id):
        """发送语音消息
        
        参数:
            to_user: 接收者的OpenID
            media_id: 语音消息媒体id，通过上传临时素材获取
            
        注意:
            语音文件的media_id有效期为3天
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送语音消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "voice",
            "voice": {
                "media_id": media_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送语音消息失败: {result.get('errmsg', '未知错误')}")

    def send_video_message(self, to_user, media_id, thumb_media_id, title="", description=""):
        """发送视频消息
        
        参数:
            to_user: 接收者的OpenID
            media_id: 视频消息媒体id，通过上传临时素材获取
            thumb_media_id: 视频消息缩略图的媒体id，通过上传临时素材获取
            title: 视频消息的标题，可选
            description: 视频消息的描述，可选
            
        注意:
            视频和缩略图的media_id有效期为3天
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送视频消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "video",
            "video": {
                "media_id": media_id,
                "thumb_media_id": thumb_media_id,
                "title": title,
                "description": description
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送视频消息失败: {result.get('errmsg', '未知错误')}")
            
    def send_music_message(self, to_user, musicurl, hqmusicurl, thumb_media_id, title="", description=""):
        """发送音乐消息
        
        参数:
            to_user: 接收者的OpenID
            musicurl: 音乐链接
            hqmusicurl: 高质量音乐链接，WIFI环境优先使用该链接播放音乐
            thumb_media_id: 缩略图的媒体id，通过上传临时素材获取
            title: 音乐标题，可选
            description: 音乐描述，可选
            
        注意:
            缩略图的media_id有效期为3天
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送音乐消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "music",
            "music": {
                "title": title,
                "description": description,
                "musicurl": musicurl,
                "hqmusicurl": hqmusicurl,
                "thumb_media_id": thumb_media_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送音乐消息失败: {result.get('errmsg', '未知错误')}")
            
    def send_news_message(self, to_user, title, description, url, picurl):
        """发送图文消息（点击跳转到外链）
        
        参数:
            to_user: 接收者的OpenID
            title: 图文消息标题
            description: 图文消息描述
            url: 点击后跳转的链接
            picurl: 图文消息的图片链接，支持JPG、PNG格式
            
        注意:
            图文消息条数限制在1条以内，如果图文数超过1，则将会返回错误码45008
        """
        if not self.access_token:
            self.get_access_token()
        url_api = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送图文消息的 URL: {url_api}")
        data = {
            "touser": to_user,
            "msgtype": "news",
            "news": {
                "articles": [
                    {
                        "title": title,
                        "description": description,
                        "url": url,
                        "picurl": picurl
                    }
                ]
            }
        }
        response = requests.post(url_api, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送图文消息失败: {result.get('errmsg', '未知错误')}")
            
    def send_mpnews_message(self, to_user, media_id):
        """发送图文消息（点击跳转到图文消息页面）
        
        参数:
            to_user: 接收者的OpenID
            media_id: 图文消息媒体ID，通过素材管理接口获取
            
        注意:
            图文消息条数限制在1条以内，如果图文数超过1，则将会返回错误码45008
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送图文消息(mpnews)的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "mpnews",
            "mpnews": {
                "media_id": media_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送图文消息(mpnews)失败: {result.get('errmsg', '未知错误')}")
            
    def send_mpnewsarticle_message(self, to_user, article_id):
        """发送图文消息（点击跳转到图文消息页面，使用article_id）
        
        参数:
            to_user: 接收者的OpenID
            article_id: 发布后获得的图文消息的article_id
            
        注意:
            草稿接口灰度完成后，将不再支持此前客服接口中带media_id的mpnews类型的图文消息
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送图文消息(mpnewsarticle)的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "mpnewsarticle",
            "mpnewsarticle": {
                "article_id": article_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送图文消息(mpnewsarticle)失败: {result.get('errmsg', '未知错误')}")
            
    def send_menu_message(self, to_user, head_content, menu_items, tail_content=""):
        """发送菜单消息
        
        参数:
            to_user: 接收者的OpenID
            head_content: 菜单消息的头部文字
            menu_items: 菜单项列表，每个菜单项是一个字典，包含id和content字段
                例如：[{"id": "101", "content": "满意"}, {"id": "102", "content": "不满意"}]
            tail_content: 菜单消息的尾部文字，可选
            
        注意:
            该消息仅支持已认证服务号使用，其余账号类型不允许使用
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送菜单消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "msgmenu",
            "msgmenu": {
                "head_content": head_content,
                "list": menu_items,
                "tail_content": tail_content
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送菜单消息失败: {result.get('errmsg', '未知错误')}")
            
    def send_wxcard_message(self, to_user, card_id):
        """发送卡券消息
        
        参数:
            to_user: 接收者的OpenID
            card_id: 卡券ID
            
        注意:
            客服消息接口投放卡券仅支持非自定义Code码和导入code模式的卡券
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送卡券消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "wxcard",
            "wxcard": {
                "card_id": card_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送卡券消息失败: {result.get('errmsg', '未知错误')}")
            
    def send_miniprogrampage_message(self, to_user, title, appid, pagepath, thumb_media_id):
        """发送小程序卡片消息
        
        参数:
            to_user: 接收者的OpenID
            title: 小程序卡片的标题
            appid: 小程序的appid，要求小程序的appid需要与公众号有关联关系
            pagepath: 小程序的页面路径，跟app.json中保持一致，可带参数
            thumb_media_id: 小程序卡片的封面图片，通过上传临时素材接口获取
            
        注意:
            小程序卡片的封面图片建议大小为520*416
        """
        if not self.access_token:
            self.get_access_token()
        url = f"https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token={self.access_token}"
        print(f"发送小程序卡片消息的 URL: {url}")
        data = {
            "touser": to_user,
            "msgtype": "miniprogrampage",
            "miniprogrampage": {
                "title": title,
                "appid": appid,
                "pagepath": pagepath,
                "thumb_media_id": thumb_media_id
            }
        }
        response = requests.post(url, data=json.dumps(data, ensure_ascii=False).encode('utf-8'))
        result = response.json()
        if result.get('errcode') != 0:
            raise Exception(f"发送小程序卡片消息失败: {result.get('errmsg', '未知错误')}")

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
        #print(f"获取关注者列表的结果: {result}")

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

        # 初始化存储所有openid的列表
        all_followers = []
        if 'data' in result and 'openid' in result['data']:
            all_followers.extend(result['data'])
        
        # 如果next_openid不为空，继续获取下一批关注者
        next_openid = result.get('next_openid')
        while next_openid:
            print(f"继续获取下一批关注者，next_openid: {next_openid}")
            result = self.get_followers(next_openid)
            if 'data' in result and 'openid' in result['data']:
                all_followers.extend(result['data'])
            next_openid = result.get('next_openid')
            
            # 如果next_openid为空或者与上一次相同，说明已经获取完毕
            if not next_openid or next_openid == result.get('next_openid'):
                break
        
        print(f"获取公众号全部关注者列表的结果: {all_followers}")
        return all_followers
        
    def upload_temporary_media(self, media_type, media_file_path_or_cos_url):
        """上传临时素材
        
        参数:
            media_type: 媒体文件类型，可选值：image（图片）、voice（语音）、video（视频）和thumb（缩略图）
            media_file_path_or_cos_url: 媒体文件的本地路径或腾讯云COS URL
            
        返回:
            dict: 包含以下字段的字典:
            - type: 媒体文件类型
            - media_id: 媒体文件上传后的唯一标识
            - created_at: 媒体文件上传时间戳
            
        注意:
            1. 临时素材的media_id是可复用的
            2. 媒体文件在微信后台保存时间为3天，即3天后media_id失效
            3. 上传的媒体文件限制:
               - 图片（image）: 10M，支持PNG\JPEG\JPG\GIF格式
               - 语音（voice）：2M，播放长度不超过60s，支持AMR\MP3格式
               - 视频（video）：10MB，支持MP4格式
               - 缩略图（thumb）：64KB，支持JPG格式
        """
        if not self.access_token:
            self.get_access_token()
            
        url = f"https://api.weixin.qq.com/cgi-bin/media/upload?access_token={self.access_token}&type={media_type}"
        print(f"上传临时素材的 URL: {url}")
        
        # 判断是COS URL还是本地文件路径
        if media_file_path_or_cos_url.startswith('http'):
            # 从COS下载文件
            print(f"从COS下载文件: {media_file_path_or_cos_url}")
            cos_response = requests.get(media_file_path_or_cos_url)
            if cos_response.status_code != 200:
                raise Exception(f"从COS下载文件失败: HTTP {cos_response.status_code}")
            
            # 获取文件扩展名
            
            parsed_url = urlparse(media_file_path_or_cos_url)
            file_extension = os.path.splitext(parsed_url.path)[1] or '.jpg'
            filename = f"temp_media{file_extension}"
            
            # 直接使用下载的内容上传
            files = {'media': (filename, cos_response.content, cos_response.headers.get('content-type', 'image/jpeg'))}
            response = requests.post(url, files=files)
        else:
            # 本地文件路径
            print(f"使用本地文件: {media_file_path_or_cos_url}")
            with open(media_file_path_or_cos_url, 'rb') as media_file:
                files = {'media': media_file}
                response = requests.post(url, files=files)
            
        result = response.json()
        print(f"上传临时素材的结果: {result}")
        
        if 'errcode' in result:
            raise Exception(f"上传临时素材失败: {result.get('errmsg', '未知错误')}")
            
        return result
    
    def get_temporary_media(self, media_id):
        """获取临时素材
        
        参数:
            media_id: 媒体文件ID
            
        返回:
            对于图片、语音、缩略图：返回文件的二进制内容
            对于视频：返回包含视频下载链接的字典 {"video_url": "下载链接"}
            
        注意:
            临时素材的media_id在微信服务器上保存3天，3天后media_id失效
        """
        if not self.access_token:
            self.get_access_token()
            
        url = f"https://api.weixin.qq.com/cgi-bin/media/get?access_token={self.access_token}&media_id={media_id}"
        print(f"获取临时素材的 URL: {url}")
        
        response = requests.get(url)
        
        # 检查是否是JSON错误响应
        if response.headers.get('Content-Type') == 'application/json' or response.headers.get('Content-Type') == 'text/plain':
            try:
                result = response.json()
                if 'errcode' in result:
                    raise Exception(f"获取临时素材失败: {result.get('errmsg', '未知错误')}")
                # 如果是视频，会返回JSON格式的下载链接
                return result
            except ValueError:
                # 不是JSON格式，可能是二进制文件内容
                pass
        
        # 如果是媒体文件，直接返回二进制内容
        return response.content
        
    def download_temporary_media(self, media_id, save_path):
        """下载临时素材并保存到指定路径
        
        参数:
            media_id: 媒体文件ID
            save_path: 保存文件的本地路径，对于视频将保存为JSON文件包含下载链接
            
        返回:
            str: 保存的文件路径
        """
        content = self.get_temporary_media(media_id)
        
        if isinstance(content, dict) and 'video_url' in content:
            # 如果是视频，保存下载链接
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(content, f)
        else:
            # 对于其他媒体类型，保存二进制内容
            with open(save_path, 'wb') as f:
                f.write(content)
                
        print(f"临时素材已保存到: {save_path}")
        return save_path