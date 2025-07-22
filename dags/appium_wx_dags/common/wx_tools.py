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
from appium_wx_dags.common.mysql_tools import init_wx_chat_records_table, init_wx_friend_circle_table

# 标准库导入
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Union, Tuple

# 第三方库导入
import requests
from airflow import DAG
import paramiko
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException

# 自定义库导入
from utils.wechat_channl import save_wx_image
from utils.wechat_channl import send_wx_image
from utils.wechat_channl import save_wx_audio

# 第三方库导入
from smbclient import register_session, open_file

logger = logging.getLogger(__name__)
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

def update_wx_user(wxid: str) -> dict:
    # 初始化新用户的聊天记录表
    try:
        init_wx_chat_records_table(wxid)
    except Exception as error:
        print(f"[WATCHER] 初始化新用户聊天记录表失败: {error}")

    # 初始化新用户的朋友圈分析表
    try:
        init_wx_friend_circle_table(wxid)
    except Exception as error:
        print(f"[WATCHER] 初始化新用户朋友圈分析表失败: {error}")

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
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_account.update({
        'update_time': current_time,
        'create_time': current_time,  # 设置创建时间，只在账号第一次创建时记录
        'source_ip': source_ip
    })

    # 查看当前列表中是否存在同账号的，先删除旧的数据
    wx_account_list = [account for account in wx_account_list if account['wxid'] != new_account['wxid']]

    # 添加新用户
    wx_account_list.append(new_account)

    # 初始化新用户的一些常用的变量
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_enable_ai_room_ids", [], serialize_json=True)
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_disable_ai_room_ids", [], serialize_json=True)
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_ui_input_prompt", "")
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_dify_api_key", "app-qKIPKEM5uzaGW0AFzAobz2Td")
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_human_room_ids", [], serialize_json=True)
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_single_chat_ai_global", "off")
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_group_chat_ai_global", "off")

    # 初始化新用户的配置（后面改成这个变量来管理配置）
    Variable.set(f"{new_account['name']}_{new_account['wxid']}_configs", 
                 {
                    "enable_ai_room_ids": [],
                    "disable_ai_room_ids": [],
                    "ui_input_prompt": "",
                    "dify_api_key": "app-qKIPKEM5uzaGW0AFzAobz2Td",
                    "human_room_ids": [],
                    "single_chat_ai_global": "off",
                    "group_chat_ai_global": "off"
                 }, 
                 serialize_json=True)

    # 初始化新用户的聊天记录表
    try:
        init_wx_chat_records_table(new_account['wxid'])
    except Exception as error:
        print(f"[WATCHER] 初始化新用户聊天记录表失败: {error}")

    # 更新用户列表
    print(f"新用户, 更新用户信息: {new_account}")
    Variable.set("WX_ACCOUNT_LIST", wx_account_list, serialize_json=True)

    # 返回新用户信息
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

    # 如果联系人名称不存在，则使用wxid作为联系人名称
    if not contact_name:
        contact_name = wxid

    print(f"返回联系人名称, wxid: {wxid}, 名称: {contact_name}")
    return contact_name



def download_cos_to_host(
    cos_url: str,
    host_address: str,
    host_username: str,
    host_password: Optional[str] = None,
    host_key_path: Optional[str] = None,
    host_port: int =None,
    host_save_path: Optional[str] = None
) -> Optional[str]:
    """
    通过SSH在主机上执行命令，直接从腾讯云COS下载文件到主机
    
    Args:
        cos_url: COS对象的URL（带签名的临时URL）
        host_address: 主机IP地址
        host_username: 主机用户名
        host_password: 主机密码（与host_key_path二选一）
        host_key_path: SSH密钥路径（与host_password二选一）
        host_port: SSH端口，默认为22
        host_save_path: 主机上的保存路径
        
    Returns:
        str: 主机上的文件路径，失败则返回None
    """
    try:
        # 创建SSH客户端
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 连接主机
        if host_key_path:
            private_key = paramiko.RSAKey.from_private_key_file(host_key_path)
            ssh.connect(host_address, username=host_username, pkey=private_key,port=host_port)
            logger.info(f"使用SSH密钥连接到主机 {host_address}")
        else:
            ssh.connect(host_address, username=host_username, password=host_password,port=host_port)
            logger.info(f"使用密码连接到主机 {host_address}")
        
        # 确定保存路径
        if not host_save_path:
            # 获取用户主目录
            stdin, stdout, stderr = ssh.exec_command("echo $HOME")
            home_dir = stdout.read().decode().strip()
            host_save_path = os.path.join(home_dir, "cos_downloads")
            
            # 确保目录存在
            ssh.exec_command(f"mkdir -p {host_save_path}")
            logger.info(f"在主机上创建目录: {host_save_path}")
        
        # 提取文件名
        filename = cos_url.split('/')[-1].split('?')[0]
        file_path = os.path.join(host_save_path, filename)
        
        # 使用curl下载
        command = f"curl -s --globoff -o {file_path} '{cos_url}'"
        logger.info(f"在主机上执行: {command}")
        stdin, stdout, stderr = ssh.exec_command(command)
        
        # 检查是否成功
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            error = stderr.read().decode()
            logger.error(f"下载失败: {error}")
            raise Exception(f"下载失败: {error}")
        
        # 确认文件存在
        stdin, stdout, stderr = ssh.exec_command(f"ls -l {file_path}")
        if not stdout.read():
            logger.error(f"文件下载失败，{file_path}不存在")
            raise Exception(f"文件下载失败，{file_path}不存在")
        
        # 关闭连接
        ssh.close()
        
        logger.info(f"文件已成功下载到主机: {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"下载文件到主机失败: {str(e)}")
        return None


def transfer_from_host_to_device(
    host_address: str,
    host_username: str,
    device_id: str,
    host_file_path: str,
    device_path: str = "/sdcard/Pictures/",
    host_password: Optional[str] = None,
    host_key_path: Optional[str] = None,
    host_port: int=None
) -> Optional[str]:
    """
    通过SSH在主机上执行ADB命令，将文件传输到手机
    
    Args:
        host_address: 主机IP地址
        host_username: 主机用户名
        device_id: 设备ID
        host_file_path: 主机上的文件路径
        device_path: 手机上的保存路径，默认为/sdcard/Pictures/
        host_password: 主机密码（与host_key_path二选一）
        host_key_path: 主机SSH密钥路径（与host_password二选一）
        host_port: SSH端口，默认为22
        
    Returns:
        str: 手机上的文件路径，失败则返回None
    """
    try:
        # 创建SSH客户端
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 连接主机
        if host_key_path:
            private_key = paramiko.RSAKey.from_private_key_file(host_key_path)
            ssh.connect(host_address, username=host_username, pkey=private_key,port=host_port)
            logger.info(f"使用SSH密钥连接到主机 {host_address}")
        else:
            ssh.connect(host_address, username=host_username, password=host_password,port=host_port)
            logger.info(f"使用密码连接到主机 {host_address}")
        
        # 构建ADB命令
        filename = os.path.basename(host_file_path)
        target_path = f"{device_path}{filename}"
        push_command = f"adb -s {device_id} push {host_file_path} {target_path}"
        refresh_command=f"adb -s {device_id} shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/Camera/"
        
        # 执行ADB命令
        logger.info(f"在主机上执行上传命令: {push_command}")
        stdin, stdout, stderr = ssh.exec_command(push_command)
        
        # 检查结果
        exit_status = stdout.channel.recv_exit_status()
        error = stderr.read().decode()
        if exit_status != 0 or ("error" in error.lower() and len(error) > 0):
            logger.error(f"上传失败: {error}")
            raise Exception(f"上传失败: {error}")
        
        # 执行刷新命令
        logger.info(f"在主机上执行刷新命令: {refresh_command}")
        refresh_stdin, refresh_stdout, refresh_stderr = ssh.exec_command(refresh_command)
        
        # 检查刷新结果
        refresh_exit_status = refresh_stdout.channel.recv_exit_status()
        refresh_error = refresh_stderr.read().decode()
        if refresh_exit_status != 0 or ("error" in refresh_error.lower() and len(refresh_error) > 0):
            logger.error(f"刷新失败: {refresh_error}")
            raise Exception(f"刷新失败: {refresh_error}")
        
        # 关闭连接
        ssh.close()
        
        logger.info(f"文件已成功传输到手机: {target_path}")
        return target_path
        
    except Exception as e:
        logger.error(f"传输文件到手机失败: {str(e)}")
        return None


def cos_to_device_via_host(
    cos_url: str,
    host_address: str,
    host_username: str,
    device_id: str,
    host_password: Optional[str] = None,
    host_key_path: Optional[str] = None,
    host_port: int =None,
    host_save_path: Optional[str] = None,
    device_path: str = "/sdcard/DCIM/Camera/",
    delete_after_transfer: bool = False,
    max_retries: int = 3
) -> Optional[str]:
    """
    完整流程：从腾讯云COS下载到主机，再从主机传输到手机
    
    Args:
        cos_url: COS预签名URL
        host_address: 主机IP地址
        host_username: 主机用户名
        device_id: 设备ID
        host_password: 主机密码（与host_key_path二选一）
        host_key_path: SSH密钥路径（与host_password二选一）
        host_save_path: 主机上的保存路径
        device_path: 手机上的保存路径，默认为/sdcard/Pictures/
        delete_after_transfer: 传输后是否删除主机上的文件
        max_retries: 从COS下载到主机的最大重试次数，默认为3次
        
    Returns:
        str: 手机上的文件路径，失败则返回None
    """
    try:
        print(f"从COS下载到主机: {cos_url}",host_address,host_username,host_password,host_key_path,host_port,host_save_path)
        
        # 步骤1：从COS下载到主机（带重试机制）
        host_file_path = None
        for attempt in range(max_retries):
            try:
                logger.info(f"尝试从COS下载到主机 (第{attempt + 1}次/共{max_retries}次)")
                host_file_path = download_cos_to_host(
                    cos_url=cos_url,
                    host_address=host_address,
                    host_username=host_username,
                    host_password=host_password,
                    host_key_path=host_key_path,
                    host_port=host_port,
                    host_save_path=host_save_path
                )
                
                if host_file_path:
                    logger.info(f"从COS下载到主机成功 (第{attempt + 1}次尝试)")
                    break
                else:
                    logger.warning(f"从COS下载到主机失败 (第{attempt + 1}次尝试)")
                    if attempt < max_retries - 1:
                        logger.info(f"等待2秒后进行第{attempt + 2}次重试...")
                        import time
                        time.sleep(2)
                    
            except Exception as e:
                logger.error(f"从COS下载到主机异常 (第{attempt + 1}次尝试): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"等待2秒后进行第{attempt + 2}次重试...")
                    import time
                    time.sleep(2)
                else:
                    logger.error(f"从COS下载到主机失败，已达到最大重试次数({max_retries}次)")
        
        if not host_file_path:
            logger.error(f"从COS下载到主机最终失败，已重试{max_retries}次")
            return None
        
        # 步骤2：从主机传输到手机
        device_file_path = transfer_from_host_to_device(
            host_address=host_address,
            host_username=host_username,
            device_id=device_id,
            host_file_path=host_file_path,
            device_path=device_path,
            host_password=host_password,
            host_key_path=host_key_path,
            host_port=host_port
        )
        
        if not device_file_path:
            logger.error("从主机传输到手机失败")
            return None
        
        # 步骤3：如果需要，删除主机上的文件
        if delete_after_transfer:
            try:
                # 创建SSH客户端
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                # 连接主机
                if host_key_path:
                    private_key = paramiko.RSAKey.from_private_key_file(host_key_path)
                    ssh.connect(host_address, port=host_port, username=host_username, pkey=private_key)
                else:
                    ssh.connect(host_address, port=host_port, username=host_username, password=host_password)
                
                # 删除文件
                ssh.exec_command(f"rm {host_file_path}")
                logger.info(f"已删除主机上的文件: {host_file_path}")
                
                # 关闭连接
                ssh.close()
            except Exception as e:
                logger.warning(f"删除主机上的文件失败: {str(e)}")
        
        return device_file_path
        
    except Exception as e:
        logger.error(f"完整传输流程失败: {str(e)}")
        return None



def upload_image_to_cos(image_file_path: str, wx_user_name: str, wx_user_id: str, room_id: str, context=None):
    """
    上传图片到COS存储
    
    Args:
        image_file_path: 本地图片路径
        wx_user_name: 微信用户名
        wx_user_id: 微信用户ID
        room_id: 房间ID
        context: Airflow上下文，用于xcom_push
        
    Returns:
        str: COS路径
    """
    # 构建COS存储路径
    cos_path = f"{wx_user_name}_{wx_user_id}/{room_id}/{os.path.basename(image_file_path)}"
    try:
        from utils.tecent_cos import upload_file
        upload_response = upload_file(image_file_path, cos_path)
        print(f"上传图片到COS成功: {cos_path}")
        # 保存COS路径到xcom中，方便后续使用
        if context and 'task_instance' in context:
            context['task_instance'].xcom_push(key='image_cos_path', value=cos_path)
        return cos_path
    except Exception as e:
        print(f"上传图片到COS失败: {str(e)}")
        # 即使COS上传失败，也返回构建的路径
        return cos_path


def check_ai_enable(wx_user_name: str, wx_user_id: str, room_id: str, is_group: bool) -> bool:
    """
    检查AI是否开启
    
    四种全局方向:
    1. 单聊全部开启
    2. 单聊全部关闭
    3. 群聊全部开启
    4. 群聊全部关闭
    
    单个会话的开关优先级高于全局设置
    """
    # 获取单个会话设置
    enable_rooms = Variable.get(f"{wx_user_name}_{wx_user_id}_enable_ai_room_ids", default_var=[], deserialize_json=True)
    disable_rooms = Variable.get(f"{wx_user_name}_{wx_user_id}_disable_ai_room_ids", default_var=[], deserialize_json=True)
    
    # 获取全局设置
    single_chat_global = Variable.get(f"{wx_user_name}_{wx_user_id}_single_chat_ai_global", default_var="off")
    group_chat_global = Variable.get(f"{wx_user_name}_{wx_user_id}_group_chat_ai_global", default_var="off")
    
    print(f"个人会话全局设置: {single_chat_global}, 群聊全局设置: {group_chat_global}")
    print(f"显式开启AI的会话: {enable_rooms}")
    print(f"显式关闭AI的会话: {disable_rooms}")
    
    # 检查是否有单个会话的特殊设置 (优先级最高)
    if room_id in enable_rooms:
        print(f"会话 {room_id} 被显式设置为开启AI")
        return True
    
    if room_id in disable_rooms:
        print(f"会话 {room_id} 被显式设置为关闭AI")
        return False
    
    # 如果没有单个会话设置，则使用全局设置
    if is_group:
        # 群聊使用群聊全局设置
        print(f"群聊消息，使用全局设置: {group_chat_global}")
        return group_chat_global == "on"
    else:
        # 单聊使用单聊全局设置
        print(f"单聊消息，使用全局设置: {single_chat_global}")
        return single_chat_global == "on"


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
