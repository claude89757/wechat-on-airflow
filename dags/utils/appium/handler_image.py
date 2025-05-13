import time
import os
import paramiko  # 添加SSH客户端库

from selenium.webdriver.support import expected_conditions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait


# def get_image_path(device_ip, username, password, device_serial, port=22):
#     """
#     获取设备中最新图片的路径
#     :param device_ip: 设备IP
#     :param username: 用户名
#     :param password: 密码
#     :param device_serial: 设备序列号
#     :param port: SSH端口号，默认22
#     :return: 最新图片的路径
#     """
#     # 微信存储图片目录
#     wx_image_dir = "/sdcard/Pictures/WeiXin" # （在红米7A上测试得到此路径）//TODO 待确认其他设备上的路径

#     # 创建SSH客户端
#     ssh_client = paramiko.SSHClient()
#     try:
#         # 自动添加主机密钥
#         ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

#         # 连接到远程服务器
#         ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)
        
#         # 构建adb shell命令（指定设备） 
#         adb_command = f"bash -l -c 'adb -s {device_serial} shell ls -t {wx_image_dir}' "
#         # 执行命令
#         stdin, stdout, stderr = ssh_client.exec_command(adb_command)

#         # 获取命令输出
#         output = stdout.read().decode('utf-8')
#         error = stderr.read().decode('utf-8')

#         # 检查命令是否成功执行
#         if error:
#             print(f"Failed to get image path: {error}")
#             return None
#         else:
#             return wx_image_dir + "/" + output.split("\n")[0]

#     except Exception as e:
#         print(f"An error occurred: {e}")
#         return None
#     finally:
#         # 确保无论如何都会关闭SSH连接
#         if ssh_client:
#             ssh_client.close()
#             print("SSH connection closed")

# def save_image(driver, element):
#     """
#     保存图片到本地
#     :return:
#     """
#     try:
#         element.click()
#         time.sleep(1)
#         WebDriverWait(driver, 60).until(
#             expected_conditions.presence_of_element_located((AppiumBy.ACCESSIBILITY_ID, '更多信息'))).click()

#         WebDriverWait(driver, 60). \
#             until(expected_conditions.presence_of_element_located((AppiumBy.XPATH,
#                                                                         f'//*[@text="保存图片"]'))).click()
#         # 返回聊天页面
#         driver.press_keycode(4)

#     except Exception as e:
#         print(f"An error occurred: {e}")

# def pull_image_from_device(device_ip, username, password, device_serial, device_path, local_path, port=22):
#     """
#     ssh远程执行adb pull命令
#     :param device_ip: 设备IP
#     :param username: 用户名
#     :param password: 密码
#     :param device_serial: 设备序列号
#     :param device_path: 设备中的文件路径
#     :param local_path: 本地保存文件的路径
#     :param port: SSH端口号，默认22
#     """

#     # 创建SSH客户端
#     ssh_client = paramiko.SSHClient()
#     try:
#         # 自动添加主机密钥
#         ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#         # 连接到远程服务器
#         ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)
        
#         # 确保远程服务器上的目标目录存在
#         local_dir = os.path.dirname(local_path)
#         if local_dir:  # 如果local_path包含目录路径
#             mkdir_command = f"mkdir -p {local_dir}" 
#             stdin, stdout, stderr = ssh_client.exec_command(mkdir_command)
#             error = stderr.read().decode('utf-8')
#             if error:
#                 print(f"Failed to create directory on remote server: {error}")
        
#         # 构建adb shell命令（指定设备）
#         adb_command = f"bash -l -c 'adb -s {device_serial} pull {device_path} {local_path}' "
        
#         # 执行命令
#         stdin, stdout, stderr = ssh_client.exec_command(adb_command)
        
#         # 获取命令输出
#         output = stdout.read().decode('utf-8')
#         error = stderr.read().decode('utf-8')
        
#         # 检查命令是否成功执行
#         if error and "No such file or directory" in error:
#             print(f"Failed to pull file: {error}")
#             return None
#         elif error:
#             print(f"Warning during pull file: {error}")
#         else:
#             print(f"File pulled successfully from {device_path} to {local_path}")
#             print(f"Command output: {output}")
#             return local_path
            
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         return None
#     finally:
#         # 确保无论如何都会关闭SSH连接
#         if ssh_client:
#             ssh_client.close()
#             print("SSH connection closed")

# def push_image_to_device(device_ip, username, password, device_serial, local_path, device_path, port=22):
#     """
#     ssh远程执行adb pull命令
#     :param device_ip: 设备IP
#     :param username: 用户名
#     :param password: 密码
#     :param device_serial: 设备序列号
#     :param device_path: 设备中的文件路径
#     :param local_path: 本地保存文件的路径
#     :param port: SSH端口号，默认22
#     """

#     # 创建SSH客户端
#     ssh_client = paramiko.SSHClient()
#     try:
#         # 自动添加主机密钥
#         ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
#         # 连接到远程服务器
#         ssh_client.connect(hostname=device_ip, username=username, password=password, port=port)

#         # 提取文件名，拼接到微信图片目录
#         filename = os.path.basename(device_path)
#         wx_image_dir = "/sdcard/Pictures/WeiXin"
#         device_path = f"{wx_image_dir}/{filename}"
        
#         # 构建adb shell命令（指定设备） 
#         adb_command = f"bash -l -c 'adb -s {device_serial} push {local_path} {device_path}' "
        
#         # 执行命令
#         stdin, stdout, stderr = ssh_client.exec_command(adb_command)
        
#         # 获取命令输出
#         output = stdout.read().decode('utf-8')
#         error = stderr.read().decode('utf-8')
        
#         # 检查命令是否成功执行
#         if error and "No such file or directory" in error:
#             print(f"Failed to puss file: {error}")
#             return None
#         elif error:
#             print(f"Warning during puss file: {error}")
#         else:
#             print(f"File pushed successfully from {local_path} to {device_path}")
#             print(f"Command output: {output}")
#             return local_path
            
#     except Exception as e:
#         print(f"An error occurred: {e}")
#         return None
#     finally:
#         # 确保无论如何都会关闭SSH连接
#         if ssh_client:
#             ssh_client.close()
#             print("SSH connection closed")
