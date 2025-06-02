#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
import time

# 第三方库导入
from airflow.models import Variable
from smbclient import register_session, open_file


def download_file_from_windows_server(server_ip: str, remote_file_name: str, local_file_name: str, max_retries: int = 3, retry_delay: int = 5):
    """从SMB服务器下载文件
    
    Args:
        remote_file_name: 远程文件名
        local_file_name: 本地文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 本地文件路径
    """
    # 创建临时目录用于存储下载的文件
    temp_dir = "/tmp/video_downloads"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 从Airflow变量获取配置
    windows_server_password = Variable.get("AI_TENNIS_WINDOWS_SERVER_PASSWORD")

    # 注册SMB会话
    try:
        register_session(
            server=server_ip,
            username="administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径和本地路径
    remote_path = f"//{server_ip}{remote_file_name.replace('C:', '/')}"
    print(f"remote_path: {remote_path}")
    local_path = os.path.join(temp_dir, local_file_name)  # 修改为使用临时目录

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

    return local_path  # 返回完整的本地文件路径


def upload_file_to_windows_server(server_ip: str, local_file_path: str, remote_file_name: str, max_retries: int = 3, retry_delay: int = 5):
    """上传文件到SMB服务器
    
    Args:
        local_file_path: 本地文件路径
        remote_file_name: 远程文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 远程文件的完整路径
    """
    # 从Airflow变量获取配置
    windows_server_password = Variable.get("AI_TENNIS_WINDOWS_SERVER_PASSWORD")

    # 注册SMB会话
    try:
        register_session(
            server=server_ip,
            username="administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径
    remote_path = f"//{server_ip}/Users/Administrator/Downloads/{remote_file_name}"

    # 执行文件上传
    for attempt in range(max_retries):
        try:
            with open(local_file_path, "rb") as local_file:
                with open_file(remote_path, mode="wb") as remote_file:
                    while True:
                        data = local_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        remote_file.write(data)
            
            print(f"文件成功上传到: {remote_path}")
            return f"C:/Users/Administrator/Downloads/{remote_file_name}"  # 返回Windows格式的路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次上传失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件上传失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常
