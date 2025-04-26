import time
import os
import datetime
import subprocess
import paramiko  # 添加SSH客户端库
from paramiko import SFTPClient

from selenium.webdriver.support import expected_conditions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from xml.etree import ElementTree

def is_video_time_less_than_x_seconds(time_text: str, max_seconds: int = 15) -> bool:
    """
    判断视频时间长度是否小于30秒
    :param time_text: 视频时间文本，格式为 "MM:SS"
    :return: 如果视频时间小于30秒，返回True；否则返回False
    """
    try:
        minutes, seconds = map(int, time_text.split(':'))
        total_seconds = minutes * 60 + seconds
        return total_seconds < max_seconds
    except ValueError:
        print("Invalid time format")
        return False

def save_video(driver, element):
    """
    保存视频到本地
    :return:
    """
    video_time_text = element.text
    max_seconds = 60
    if is_video_time_less_than_x_seconds(video_time_text, max_seconds=max_seconds):
        element.click()
        time.sleep(1)
        WebDriverWait(driver, 60).until(
            expected_conditions.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, '更多信息'))).click()

        WebDriverWait(driver, 60). \
            until(expected_conditions.presence_of_element_located((AppiumBy.XPATH,
                                                                    f'//*[@text="保存视频"]'))).click()
        # 获取当前页面的 XML 结构
        page_source = driver.page_source
        # 解析 XML
        tree = ElementTree.fromstring(page_source)
        # 查找所有元素
        all_elements = tree.findall(".//*")
        print("Clickable elements on the current page:")
        for elem in all_elements:
            text = elem.attrib.get('text', 'N/A')
            if "视频已保存至" in text:
                # 获取视频保存路径
                video_path = text.split("视频已保存至")[-1].strip()
                print(f"[INFO] 视频已保存至: {video_path}")
                # 返回到聊天页面
                driver.press_keycode(4)  # Android返回键
                print("[INFO] 已使用物理返回键，返回聊天页面")
                return video_path
            else:
                pass
        raise Exception(f"视频不见了？")
    else:
        print("The video time is not less than 30 seconds.")
        raise Exception(f"视频时长超过{max_seconds}秒, 太长了")


def load_data_from_local_file(filename: str, expire_time: int = 72000):
    """
    从本地文件读取数据，若不存在或超时，则重新拉取
    """
    file_path = f"./{filename}"
    with open(file_path, 'r') as f:
        local_data = f.read().strip()
    # 获取文件的最后修改时间
    file_mod_time = os.path.getmtime(file_path)
    file_mod_date = datetime.datetime.fromtimestamp(file_mod_time)
    # 计算文件的年龄
    file_age_seconds = (datetime.datetime.now() - file_mod_date).seconds
    print(f"{file_path}: {file_mod_date}")

    if file_age_seconds > expire_time:
        print(f"data is expired, delete old data for {filename}")
        return ""
    else:
        return local_data


def clear_mp4_files_in_directory(device_ip, username, password, device_serial, directory_path, port=22):
    """
    通过SSH远程执行命令清理指定目录下的所有MP4文件，并触发媒体库更新。
    :param device_ip: 设备IP
    :param username: 用户名
    :param password: 密码
    :param device_serial: 设备序列号
    :param directory_path: 设备中的目录路径
    :param port: SSH端口号，默认22
    """
    # 创建SSH客户端
    ssh_client = paramiko.SSHClient()
    try:
        # 自动添加主机密钥
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # 连接到远程服务器
        ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)

        # 列出目录下所有的mp4文件（指定设备）
        list_command = f'adb -s {device_serial} shell ls {directory_path}/*.mp4'
        stdin, stdout, stderr = ssh_client.exec_command(list_command)
        
        # 获取命令输出
        file_list_output = stdout.read().decode('utf-8')
        list_error = stderr.read().decode('utf-8')

        if list_error:
            print(f"Error listing files: {list_error}")
            return

        # 获取文件列表
        file_list = file_list_output.strip().split('\n')
        if file_list == ['']:
            print("No MP4 files found.")
            return

        # 删除每个文件
        for file in file_list:
            if file.strip():  # 确保文件名不是空字符串
                delete_command = f'adb -s {device_serial} shell rm "{file}"'
                stdin, stdout, stderr = ssh_client.exec_command(delete_command)
                
                # 获取删除命令输出
                delete_output = stdout.read().decode('utf-8')
                delete_error = stderr.read().decode('utf-8')
                
                if not delete_error:
                    print(f"Deleted {file}")
                else:
                    print(f"Failed to delete {file}: {delete_error}")

        # 触发媒体扫描更新媒体库（指定设备）
        scan_command = f'adb -s {device_serial} shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{directory_path}'
        stdin, stdout, stderr = ssh_client.exec_command(scan_command)
        
        # 获取扫描命令输出
        scan_output = stdout.read().decode('utf-8')
        scan_error = stderr.read().decode('utf-8')
        
        if not scan_error:
            print("Media scan triggered successfully.")
        else:
            print(f"Failed to trigger media scan: {scan_error}")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # 确保无论如何都会关闭SSH连接
        if ssh_client:
            ssh_client.close()
            print("SSH connection closed")


def pull_file_from_device(device_ip, username, password, device_serial, device_path, local_path, port=22):
    """
    ssh远程执行adb pull命令
    :param device_ip: 设备IP
    :param username: 用户名
    :param password: 密码
    :param device_serial: 设备序列号
    :param device_path: 设备中的文件路径
    :param local_path: 本地保存文件的路径
    :param port: SSH端口号，默认22
    """
    # 创建SSH客户端
    ssh_client = paramiko.SSHClient()
    try:
        # 自动添加主机密钥
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # 连接到远程服务器
        ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)
        
        # 确保远程服务器上的目标目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir:  # 如果local_path包含目录路径
            mkdir_command = f"mkdir -p {local_dir}"
            stdin, stdout, stderr = ssh_client.exec_command(mkdir_command)
            error = stderr.read().decode('utf-8')
            if error:
                print(f"Failed to create directory on remote server: {error}")
        
        # 构建adb pull命令（指定设备）
        adb_command = f"adb -s {device_serial} pull {device_path} {local_path}"
        
        # 执行命令
        stdin, stdout, stderr = ssh_client.exec_command(adb_command)
        
        # 获取命令输出
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        # 检查命令是否成功执行
        if error and "No such file or directory" in error:
            print(f"Failed to pull file: {error}")
            return None
        elif error:
            print(f"Warning during pull file: {error}")
        else:
            print(f"File pulled successfully from {device_path} to {local_path}")
            print(f"Command output: {output}")
            return local_path
            
    except Exception as e:
        print(f"An error occurred: {e}")
        return None
    finally:
        # 确保无论如何都会关闭SSH连接
        if ssh_client:
            ssh_client.close()
            print("SSH connection closed")


def push_file_to_device(device_ip, username, password, device_serial, local_path, device_path, port=22):
    """
    ssh远程执行adb push命令
    :param device_ip: 设备IP
    :param username: 用户名
    :param password: 密码
    :param device_serial: 设备序列号
    :param local_path: 本地文件路径
    :param device_path: 设备中的保存路径
    :param port: SSH端口号，默认22
    """
    # 创建SSH客户端
    ssh_client = paramiko.SSHClient()
    try:
        # 先在远程服务器上检查本地文件是否存在
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)
        
        # 检查文件是否存在
        check_file_command = f"ls -la {local_path}"
        stdin, stdout, stderr = ssh_client.exec_command(check_file_command)
        file_check_output = stdout.read().decode('utf-8')
        file_check_error = stderr.read().decode('utf-8')
        
        if file_check_error and "No such file or directory" in file_check_error:
            print(f"错误：本地文件不存在: {local_path}")
            return False
        
        # 确保设备上的目标目录存在
        device_dir = os.path.dirname(device_path)
        if device_dir:
            # 先创建设备上的目录
            mkdir_command = f"adb -s {device_serial} shell mkdir -p {device_dir}"
            stdin, stdout, stderr = ssh_client.exec_command(mkdir_command)
            error = stderr.read().decode('utf-8')
            if error:
                print(f"警告: 在设备上创建目录失败: {error}")
        
        # 构建adb push命令（指定设备）
        adb_push_command = f"adb -s {device_serial} push {local_path} {device_path}"
        
        # 执行push命令
        stdin, stdout, stderr = ssh_client.exec_command(adb_push_command)
        
        # 获取命令输出
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        
        # 检查命令是否成功执行
        if error and "No such file or directory" in error:
            print(f"推送文件失败: {error}")
            return False
        elif "adb: error" in output or "failed to copy" in output.lower() or error:
            print(f"推送文件过程中出现警告: {error}")
            print(f"输出: {output}")
            return False
        else:
            # 检查输出是否包含成功信息
            if "pushed" in output and "100%" in output:
                print(f"文件成功推送，从 {local_path} 到 {device_path}")
                print(f"命令输出: {output}")
                
                # 构建触发媒体扫描的命令（指定设备）
                scan_command = f'adb -s {device_serial} shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{device_path}'
                
                # 执行媒体扫描命令
                stdin, stdout, stderr = ssh_client.exec_command(scan_command)
                
                # 获取扫描命令输出
                scan_output = stdout.read().decode('utf-8')
                scan_error = stderr.read().decode('utf-8')
                
                if scan_error:
                    print(f"触发媒体扫描失败: {scan_error}")
                else:
                    print("媒体扫描成功触发。")
                    print(f"扫描命令输出: {scan_output}")
                return True
            else:
                print(f"推送文件可能失败: {output}")
                return False
        
    except Exception as e:
        print(f"发生错误: {e}")
        return False
    finally:
        # 确保无论如何都会关闭SSH连接
        if ssh_client:
            ssh_client.close()
            print("SSH连接已关闭")


def upload_file_to_device_via_sftp(device_ip, username, password, local_path, device_path, port=22):
    """
    通过SSH/SFTP协议直接将本地文件上传到远程设备（树莓派或Mac系统）
    :param device_ip: 远程服务器IP
    :param username: 用户名
    :param password: 密码
    :param local_path: 本地文件路径
    :param device_path: 远程设备上的文件路径
    :param port: SSH端口号，默认22
    :return: 远程文件路径或None（如果上传失败）
    """
    # 创建SSH客户端
    ssh_client = paramiko.SSHClient()
    sftp_client = None
    try:
        # 自动添加主机密钥
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # 连接到远程服务器
        ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)
        
        # 创建SFTP客户端
        sftp_client = ssh_client.open_sftp()
        
        # 确保本地文件存在
        if not os.path.exists(local_path):
            print(f"本地文件不存在: {local_path}")
            return None
        
        # 确保远程目录存在
        remote_dir = os.path.dirname(device_path)
        if remote_dir:
            try:
                # 尝试创建远程目录（如果不存在）
                mkdir_command = f"mkdir -p {remote_dir}"
                stdin, stdout, stderr = ssh_client.exec_command(mkdir_command)
                error = stderr.read().decode('utf-8')
                if error:
                    print(f"警告: 在远程服务器上创建目录失败: {error}")
            except Exception as e:
                print(f"创建远程目录时出错: {e}")
        
        # 上传文件
        sftp_client.put(local_path, device_path)
        
        print(f"文件成功上传，从 {local_path} 到 {device_path}")
        return device_path
        
    except Exception as e:
        print(f"上传文件失败: {e}")
        return None
    finally:
        # 确保无论如何都会关闭连接
        if sftp_client:
            sftp_client.close()
            print("SFTP连接已关闭")
        if ssh_client:
            ssh_client.close()
            print("SSH连接已关闭")


def download_file_via_sftp(device_ip, username, password, remote_path, local_path, port=22):
    """
    通过SSH/SFTP协议直接从远程服务器下载文件到本地/tmp/tennis_video_output/目录
    :param device_ip: 远程服务器IP
    :param username: 用户名
    :param password: 密码
    :param remote_path: 远程文件路径
    :param local_path: 本地文件路径
    :param port: SSH端口号，默认22
    :return: 本地文件路径或None（如果下载失败）
    """
    # 创建SSH客户端
    ssh_client = paramiko.SSHClient()
    sftp_client = None
    try:
        # 自动添加主机密钥
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # 连接到远程服务器
        ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)
        
        # 创建SFTP客户端
        sftp_client = ssh_client.open_sftp()
        
        # 确保本地目录存在（注意：这是在当前执行环境中创建目录，而不是在远程服务器上）
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # 下载文件
        sftp_client.get(remote_path, local_path)
        
        print(f"File downloaded successfully from {remote_path} to {local_path}")
        return local_path
        
    except Exception as e:
        print(f"Failed to download file: {e}")
        return None
    finally:
        # 确保无论如何都会关闭连接
        if sftp_client:
            sftp_client.close()
            print("SFTP connection closed")
        if ssh_client:
            ssh_client.close()
            print("SSH connection closed")


# TEST
if __name__ == "__main__":
    pass