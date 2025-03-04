#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信工具模块
提供微信相关的工具函数,包括:
- 用户信息更新和缓存
- 联系人信息获取
- 群聊管理等

Author: claude89757
Date: 2025-01-09
"""


from datetime import datetime

from airflow.models import Variable
from utils.wechat_channl import get_wx_self_info
from utils.wechat_channl import get_wx_contact_list
from wx_dags.common.mysql_tools import init_wx_chat_records_table

# 标准库导入
import os
import time
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException

# 自定义库导入
from utils.wechat_channl import save_wx_image
from utils.wechat_channl import send_wx_image
from utils.wechat_channl import save_wx_audio

# 第三方库导入
from smbclient import register_session, open_file


# 微信消息类型定义
WX_MSG_TYPES = {
    0: "朋友圈消息",
    1: "文字",
    3: "图片", 
    34: "语音",
    37: "好友确认",
    40: "POSSIBLEFRIEND_MSG",
    42: "名片",
    43: "视频",
    47: "石头剪刀布 | 表情图片",
    48: "位置",
    49: "共享实时位置、文件、转账、链接",
    50: "VOIPMSG",
    51: "微信初始化",
    52: "VOIPNOTIFY", 
    53: "VOIPINVITE",
    62: "小视频",
    66: "微信红包",
    9999: "SYSNOTICE",
    10000: "红包、系统消息",
    10002: "撤回消息",
    1048625: "搜狗表情",
    16777265: "链接",
    436207665: "微信红包",
    536936497: "红包封面",
    754974769: "视频号视频",
    771751985: "视频号名片",
    822083633: "引用消息",
    922746929: "拍一拍",
    973078577: "视频号直播",
    974127153: "商品链接",
    975175729: "视频号直播",
    1040187441: "音乐链接",
    1090519089: "文件"
}


def update_wx_user_info(source_ip: str) -> dict:
    """
    获取用户信息，并缓存。对于新用户，会初始化其专属的 enable_ai_room_ids 列表
    """
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)

    # 遍历用户列表，获取用户信息
    for account in wx_account_list:
        if source_ip == account['source_ip']:
            print(f"获取到缓存的用户信息: {account}")
            return account
    
    # 获取最新用户信息
    new_account = get_wx_self_info(wcf_ip=source_ip)
    new_account.update({
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source_ip': source_ip
    })

    # 查看当前列表中是否存在同账号的，先删除旧的数据
    wx_account_list = [account for account in wx_account_list if account['wxid'] != new_account['wxid']]
    
    # 添加新用户
    wx_account_list.append(new_account)

    # 初始化新用户的 enable_ai_room_ids 和 disable_ai_room_ids
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_enable_ai_room_ids", [], serialize_json=True)
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_disable_ai_room_ids", [], serialize_json=True)

    # 初始化新用户的聊天记录表
    init_wx_chat_records_table(new_account['wxid'])

    print(f"新用户, 更新用户信息: {new_account}")
    Variable.set("WX_ACCOUNT_LIST", wx_account_list, serialize_json=True)
    return new_account


def get_contact_name(source_ip: str, wxid: str, wx_user_name: str) -> str:
    """
    获取联系人/群名称，使用Airflow Variable缓存联系人列表，1小时刷新一次
    wxid: 可以是sender或roomid
    """

    print(f"获取联系人/群名称, source_ip: {source_ip}, wxid: {wxid}")
    # 获取缓存的联系人列表
    cache_key = f"{wx_user_name}_CONTACT_INFOS"
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cached_data = Variable.get(cache_key, default_var={"update_time": "1970-01-01 00:00:00", "contact_infos": {}}, deserialize_json=True)
    
    # 检查是否需要刷新缓存（1小时 = 3600秒）
    cached_time = datetime.strptime(cached_data["update_time"], '%Y-%m-%d %H:%M:%S')
    if (datetime.now() - cached_time).total_seconds() > 3600:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {"update_time": current_timestamp, "contact_infos": contact_infos}
        try:
            Variable.set(cache_key, cached_data, serialize_json=True)
        except Exception as error:
            print(f"[WATCHER] 更新缓存失败: {error}")
    else:
        print(f"使用缓存的联系人列表，数量: {len(cached_data['contact_infos'])}", cached_data)

    # 返回联系人名称
    contact_name = cached_data["contact_infos"].get(wxid, {}).get('name', '')

    # 如果联系人名称不存在，则尝试刷新缓存
    if not contact_name:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {"update_time": current_timestamp, "contact_infos": contact_infos}
        try:
            Variable.set(cache_key, cached_data, serialize_json=True)
        except Exception as error:
            print(f"[WATCHER] 更新缓存失败: {error}")

        # 重新获取联系人名称
        contact_name = contact_infos.get(wxid, {}).get('name', wxid)

    print(f"返回联系人名称, wxid: {wxid}, 名称: {contact_name}")
    return contact_name


def check_ai_enable(wx_user_name: str, wx_user_id: str, room_id: str, is_group: bool) -> bool:
    """
    检查AI是否开启
    """
    # 检查房间是否开启AI - 使用用户专属的配置
    enable_rooms = Variable.get(f"{wx_user_name}_{wx_user_id}_enable_ai_room_ids", default_var=[], deserialize_json=True)
    disable_rooms = Variable.get(f"{wx_user_name}_{wx_user_id}_disable_ai_room_ids", default_var=[], deserialize_json=True)
    print(f"enable_rooms: {enable_rooms}")
    print(f"disable_rooms: {disable_rooms}")
    if is_group:
        print(f"群聊消息, 需要同时满足在开启列表中，且不在禁用列表中")
        if room_id in enable_rooms and room_id not in disable_rooms:
            ai_reply = True
        else:
            ai_reply = False
    else:
        print(f"单聊消息, 默认开启AI")
        if room_id in enable_rooms:
            ai_reply = True
        else:
            ai_reply = False

    return ai_reply


def download_image_from_windows_server(source_ip: str, msg_id: str, extra: str, max_retries: int = 2, retry_delay: int = 5):
    """从SMB服务器下载文件到服务器本地
    
    Args:
        remote_file_name: 远程文件名
        local_file_name: 本地文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 本地文件路径
    """
    # 保存图片到微信客户端侧
    save_dir = f"C:/Users/Administrator/Downloads/"
    image_file_path = save_wx_image(wcf_ip=source_ip, id=msg_id, extra=extra, save_dir=save_dir, timeout=30)
    remote_image_file_name = os.path.basename(image_file_path)
    print(f"image_file_path: {image_file_path}")

    # 等待3秒
    time.sleep(3)

    # 注册SMB会话
    windows_user_name = "Administrator"
    windows_server_password = Variable.get("WINDOWS_SERVER_PASSWORD")
    try:
        register_session(
            server=source_ip,
            username=windows_user_name,
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 创建临时目录用于存储下载的文件
    temp_dir = "/tmp/image_downloads"
    os.makedirs(temp_dir, exist_ok=True) 

    # 构建远程路径和本地路径
    local_new_file_name = f"{msg_id}.jpg"
    remote_path = f"//{source_ip}/Users/{windows_user_name}/Downloads/{remote_image_file_name}"
    local_path = os.path.join(temp_dir, local_new_file_name)  # 修改为使用临时目录
    # 执行文件下载
    for attempt in range(max_retries):
        try:
            with open_file(remote_path, mode="rb") as remote_file:
                with open(local_path, "wb") as local_file:
                    while True:
                        data = remote_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        local_file.write(data)
            print(f"文件成功下载到: {os.path.abspath(local_path)}")
            
            # 验证文件大小不为0
            if os.path.getsize(local_path) == 0:
                raise Exception("下载的文件大小为0字节")
                
            return local_path  # 下载成功，返回本地文件路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次下载失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件下载失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常
    
    # 返回本地文件路径
    print(f"图片已下载到本地: {local_path}")
    return local_path


def download_voice_from_windows_server(source_ip: str, msg_id: str, max_retries: int = 2, retry_delay: int = 5):
    """从SMB服务器下载语音到服务器本地
    
    Args:
        remote_file_name: 远程文件名    
        local_file_name: 本地文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 本地文件路径
    """

    # 保存语音到微信客户端侧
    save_dir = f"C:/Users/Administrator/Downloads/"
    voice_file_path = save_wx_audio(wcf_ip=source_ip, id=msg_id, save_dir=save_dir)
    remote_voice_file_name = os.path.basename(voice_file_path)
    print(f"voice_file_path: {voice_file_path}")

    # 等待3秒
    time.sleep(3)

    # 注册SMB会话
    windows_user_name = "Administrator"
    windows_server_password = Variable.get("WINDOWS_SERVER_PASSWORD")
    try:
        register_session(
            server=source_ip,
            username=windows_user_name,
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 创建临时目录用于存储下载的文件
    temp_dir = "/tmp/voice_downloads"
    os.makedirs(temp_dir, exist_ok=True) 

    # 构建远程路径和本地路径
    local_new_file_name = f"{source_ip}_{msg_id}.mp3"
    remote_path = f"//{source_ip}/Users/{windows_user_name}/Downloads/{remote_voice_file_name}"
    local_path = os.path.join(temp_dir, local_new_file_name)  # 修改为使用临时目录
    # 执行文件下载
    for attempt in range(max_retries):
        try:
            with open_file(remote_path, mode="rb") as remote_file:
                with open(local_path, "wb") as local_file:
                    while True:
                        data = remote_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        local_file.write(data)
            print(f"文件成功下载到: {os.path.abspath(local_path)}")
            
            # 验证文件大小不为0
            if os.path.getsize(local_path) == 0:
                raise Exception("下载的文件大小为0字节")
                
            return local_path  # 下载成功，返回本地文件路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次下载失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件下载失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常
    
    # 返回本地文件路径
    print(f"语音已下载到本地: {local_path}")
    return local_path
