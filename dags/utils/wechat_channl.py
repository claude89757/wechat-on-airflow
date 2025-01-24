#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import requests


def send_wx_msg(wcf_ip: str, message: str, receiver: str, aters: str = "") -> bool:
    """
    通过WCF API发送微信消息
    Args:
        wcf_ip: WCF服务器IP
        message: 要发送的消息内容
        receiver: 接收者
        aters: 要@的用户，可选
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/text"

    payload = {"msg": message, "receiver": receiver, "aters": aters}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"发送失败: {result.get('message', '未知错误')}")
    return True
        

def get_wx_contact_list(wcf_ip: str) -> list:
    """
    获取微信联系人列表
    Args:
        wcf_ip: WCF服务器IP
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/contacts"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    print(f"result: {result}")
    return result.get('data', [])


def send_wx_image(wcf_ip: str, image_path: str, receiver: str) -> bool:
    """
    通过WCF API发送图片消息
    Args:
        wcf_ip: WCF服务器IP
        image_path: 图片文件路径
        receiver: 接收者
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/image"

    payload = {"path": image_path, "receiver": receiver}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"发送图片失败: {result.get('message', '未知错误')}")
    return True


def send_wx_file(wcf_ip: str, file_path: str, receiver: str) -> bool:
    """
    通过WCF API发送文件
    Args:
        wcf_ip: WCF服务器IP
        file_path: 文件路径
        receiver: 接收者
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/file"

    payload = {"path": file_path, "receiver": receiver}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"发送文件失败: {result.get('message', '未知错误')}")
    return True


def send_wx_rich_text(wcf_ip: str, title: str, desc: str, url: str, thumb_url: str, receiver: str) -> bool:
    """
    通过WCF API发送富文本卡片消息
    Args:
        wcf_ip: WCF服务器IP
        title: 卡片标题
        desc: 卡片描述
        url: 点击跳转链接
        thumb_url: 卡片缩略图URL
        receiver: 接收者
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/rich-text"

    payload = {
        "title": title,
        "desc": desc,
        "url": url,
        "thumb_url": thumb_url,
        "receiver": receiver
    }

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"发送富文本消息失败: {result.get('message', '未知错误')}")
    return True


def get_wx_self_info(wcf_ip: str) -> dict:
    """
    获取当前登录的微信账号信息
    Args:
        wcf_ip: WCF服务器IP
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/userinfo"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"获取账号信息失败: {result.get('message', '未知错误')}")
    return result.get('data', {})


def get_wx_room_members(wcf_ip: str, room_id: str) -> list:
    """
    获取群成员列表
    Args:
        wcf_ip: WCF服务器IP
        room_id: 群聊ID
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/query-room-member"

    params = {"room_id": room_id}
    
    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Params: {params}")
    response = requests.get(wcf_api_url, params=params, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"获取群成员失败: {result.get('message', '未知错误')}")
    print(f"result: {result}")
    return result.get('data', [])


def send_wx_pat(wcf_ip: str, receiver: str, wxid: str) -> bool:
    """
    发送拍一拍消息
    Args:
        wcf_ip: WCF服务器IP
        receiver: 群ID
        wxid: 要拍的群成员wxid
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/pat"

    payload = {"receiver": receiver, "wxid": wxid}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"发送拍一拍消息失败: {result.get('message', '未知错误')}")
    return True


def forward_wx_msg(wcf_ip: str, id: int, receiver: str) -> bool:
    """
    转发消息
    Args:
        wcf_ip: WCF服务器IP
        id: 待转发消息id
        receiver: 接收者
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/forward-msg"

    payload = {"id": id, "receiver": receiver}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"转发消息失败: {result.get('message', '未知错误')}")
    return True


def save_wx_audio(wcf_ip: str, id: int, extra: str) -> str:
    """
    保存语音消息
    Args:
        wcf_ip: WCF服务器IP
        id: 消息id
        extra: 消息extra字段
    Returns:
        str: 保存后的文件路径
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/audio"

    payload = {"id": id, "extra": extra}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"保存语音失败: {result.get('message', '未知错误')}")
    return result.get('data', '')


def save_wx_image(wcf_ip: str, id: int, extra: str, save_dir: str, timeout: int = 10) -> str:
    """
    保存图片消息
    Args:
        wcf_ip: WCF服务器IP
        id: 消息id
        extra: 消息extra字段
        save_dir: 保存目录
        timeout: 超时时间(秒)
    Returns:
        str: 保存后的文件路径
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/save-image"

    payload = {
        "id": id,
        "extra": extra,
        "dir": save_dir,
        "timeout": timeout
    }

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"保存图片失败: {result.get('message', '未知错误')}")
    return result.get('data', '')


def save_wx_file(wcf_ip: str, id: int, extra: str, thumb: str = "") -> str:
    """
    保存文件消息
    Args:
        wcf_ip: WCF服务器IP
        id: 消息id
        extra: 消息extra字段
        thumb: 缩略图字段
    Returns:
        str: 保存后的文件路径
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/save-file"

    payload = {
        "id": id,
        "extra": extra,
        "thumb": thumb
    }

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"保存文件失败: {result.get('message', '未知错误')}")
    return result.get('data', '')


def receive_wx_transfer(wcf_ip: str, wxid: str, transferid: str, transactionid: str) -> bool:
    """
    接收转账
    Args:
        wcf_ip: WCF服务器IP
        wxid: 转账发送者wxid
        transferid: 转账id
        transactionid: 交易id
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/receive-transfer"

    payload = {
        "wxid": wxid,
        "transferid": transferid,
        "transactionid": transactionid
    }

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"接收转账失败: {result.get('message', '未知错误')}")
    return True


def query_wx_sql(wcf_ip: str, db: str, sql: str) -> list:
    """
    执行SQL查询
    Args:
        wcf_ip: WCF服务器IP
        db: 数据库名
        sql: SQL语句
    Returns:
        list: 查询结果
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/sql"

    payload = {"db": db, "sql": sql}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"执行SQL失败: {result.get('message', '未知错误')}")
    return result.get('data', [])


def accept_wx_new_friend(wcf_ip: str, v3: str, v4: str, scene: str) -> bool:
    """
    通过好友申请
    Args:
        wcf_ip: WCF服务器IP
        v3: v3数据
        v4: v4数据
        scene: 添加场景
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/accept-new-friend"

    payload = {"v3": v3, "v4": v4, "scene": scene}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"通过好友申请失败: {result.get('message', '未知错误')}")
    return True


def add_wx_chatroom_member(wcf_ip: str, roomid: str, wxids: list) -> bool:
    """
    添加群成员
    Args:
        wcf_ip: WCF服务器IP
        roomid: 群ID
        wxids: 要添加的成员wxid列表
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/add-chatroom-member"

    payload = {"roomid": roomid, "wxids": wxids}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"添加群成员失败: {result.get('message', '未知错误')}")
    return True


def invite_wx_chatroom_member(wcf_ip: str, roomid: str, wxids: list) -> bool:
    """
    邀请群成员
    Args:
        wcf_ip: WCF服务器IP
        roomid: 群ID
        wxids: 要邀请的成员wxid列表
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/invite-chatroom-member"

    payload = {"roomid": roomid, "wxids": wxids}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"邀请群成员失败: {result.get('message', '未知错误')}")
    return True


def delete_wx_chatroom_member(wcf_ip: str, roomid: str, wxids: list) -> bool:
    """
    删除群成员
    Args:
        wcf_ip: WCF服务器IP
        roomid: 群ID
        wxids: 要删除的成员wxid列表
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/delete-chatroom-member"

    payload = {"roomid": roomid, "wxids": wxids}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Payload: {payload}")
    response = requests.post(wcf_api_url, json=payload, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"删除群成员失败: {result.get('message', '未知错误')}")
    return True


def revoke_wx_msg(wcf_ip: str, id: int) -> bool:
    """
    撤回消息
    Args:
        wcf_ip: WCF服务器IP
        id: 待撤回消息id
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/revoke-msg"

    params = {"id": id}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Params: {params}")
    response = requests.post(wcf_api_url, params=params, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"撤回消息失败: {result.get('message', '未知错误')}")
    return True


def get_wx_dbs(wcf_ip: str) -> list:
    """
    获取所有可查询数据库
    Args:
        wcf_ip: WCF服务器IP
    Returns:
        list: 数据库列表
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/dbs"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"获取数据库列表失败: {result.get('message', '未知错误')}")
    return result.get('data', [])


def get_wx_tables(wcf_ip: str, db: str) -> list:
    """
    获取数据库中的表信息
    Args:
        wcf_ip: WCF服务器IP
        db: 数据库名
    Returns:
        list: 表信息列表
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/{db}/tables"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"获取表信息失败: {result.get('message', '未知错误')}")
    return result.get('data', [])


def get_wx_msg_types(wcf_ip: str) -> dict:
    """
    获取消息类型枚举
    Args:
        wcf_ip: WCF服务器IP
    Returns:
        dict: 消息类型枚举
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/msg-types"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"获取消息类型失败: {result.get('message', '未知错误')}")
    return result.get('data', {})


def refresh_wx_pyq(wcf_ip: str, id: int = 0) -> bool:
    """
    刷新朋友圈
    Args:
        wcf_ip: WCF服务器IP
        id: 开始id,0为最新页
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/pyq"

    params = {"id": id}

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    print(f"[WECHAT_CHANNEL] Params: {params}")
    response = requests.get(wcf_api_url, params=params, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"刷新朋友圈失败: {result.get('message', '未知错误')}")
    return True


def check_wx_login(wcf_ip: str) -> bool:
    """
    检查微信登录状态
    Args:
        wcf_ip: WCF服务器IP
    Returns:
        bool: 是否已登录
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/islogin"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"检查登录状态失败: {result.get('message', '未知错误')}")
    return result.get('data', False)


def get_wx_self_wxid(wcf_ip: str) -> str:
    """
    获取当前登录的微信wxid
    Args:
        wcf_ip: WCF服务器IP
    Returns:
        str: 当前登录的wxid
    """
    wcf_port = os.getenv("WCF_API_PORT", "9999")
    wcf_api_url = f"http://{wcf_ip}:{wcf_port}/selfwxid"

    print(f"[WECHAT_CHANNEL] wcf_api_url: {wcf_api_url}")
    response = requests.get(wcf_api_url, headers={'Content-Type': 'application/json'})
    print(f"[WECHAT_CHANNEL] response: {response.status_code} - {response.text}")
    
    response.raise_for_status()
    result = response.json()
    if result.get('status') != 0:
        raise Exception(f"获取wxid失败: {result.get('message', '未知错误')}")
    return result.get('data', '')
