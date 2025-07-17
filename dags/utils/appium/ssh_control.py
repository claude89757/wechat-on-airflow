import os
import re
import paramiko

def exec_cmd_by_ssh(host, port, username, password, cmd):
    """
    通过ssh远程执行命令
    :param host: 主机ip
    :param port: 主机ssh端口
    :param username: 主机用户名
    :param password: 主机密码
    :param cmd: 要执行的命令
    :return: 命令执行结果
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print(f'正在连接{host}:{port}...')
        ssh.connect(hostname=host, port=port, username=username, password=password)
        _, stdout, stderr = ssh.exec_command(cmd)
        print(f'命令{cmd}执行完成，返回结果')
        out = stdout.read().decode()
        err = stderr.read().decode()
        return out, err

    except Exception as e:
        print(e)
        return None, None
    finally:
        # 保证ssh连接关闭
        ssh.close()


def get_device_id_by_adb(host, port, username, password) -> list:
    '''
        通过adb命令获取设备号
        :param host: 主机地址
        :param port: 端口
        :param username: 用户名
        :param password: 密码
        :return: 设备号列表
    '''

    cmd = 'adb devices'
    # 执行adb命令
    out, _ = exec_cmd_by_ssh(host, port, username, password, cmd)

    # 解析adb命令的输出，获取设备号
    device_id_list = []
    for line in out.splitlines()[1:]:
        # 如果该行有非空字符内容
        if line.strip():
            device_id = re.split(r'\s+', line)[0]
            print(f'设备号：{device_id}') 
            device_id_list.append(device_id)
    return device_id_list


def get_image_path(device_ip, username, password, device_serial, port=22):
    """
    获取微信存储的最新图片的路径
    :param device_ip: 设备IP
    :param username: 用户名
    :param password: 密码
    :param device_serial: 设备序列号
    :param port: SSH端口号，默认22
    :return: 最新图片的路径
    """
    # 微信存储图片目录
    wx_image_dir = "/sdcard/Pictures/WeiXin" # （在红米7A上测试得到此路径）//TODO 待确认其他设备上的路径

    # 构建adb shell命令（指定设备） 
    adb_command = f"bash -l -c 'adb -s {device_serial} shell ls -t {wx_image_dir}' "

    output, error = exec_cmd_by_ssh(device_ip, port, username, password, adb_command)

    # 检查命令是否成功执行
    if error:
        print(f"Failed to get image path: {error}")
        return None
    else:
        return wx_image_dir + "/" + output.split("\n")[0]
    

def pull_image_from_device(device_ip, username, password, device_serial, device_path, local_path, port=22):
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

    # 确保远程服务器上的目标目录存在
    local_dir = os.path.dirname(local_path)
    if local_dir:  # 如果local_path包含目录路径
        mkdir_command = f"mkdir -p {local_dir}" 
        _, error = exec_cmd_by_ssh(device_ip, port, username, password, mkdir_command)
        if error:
            print(f"Failed to create directory on remote server: {error}")

    # 构建adb shell命令（指定设备）
    adb_command = f"bash -l -c 'adb -s {device_serial} pull {device_path} {local_path}' "
    
    # 执行命令
    output, error = exec_cmd_by_ssh(device_ip, port, username, password, adb_command)
   
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
    

def push_image_to_device(device_ip, username, password, device_serial, local_path, device_path, port=22):
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

    # 提取文件名，拼接到微信图片目录
    filename = os.path.basename(device_path)
    wx_image_dir = "/sdcard/Pictures/WeiXin"
    wx_image_dir_wc = "/sdcard/Pictures/WeChat"
    device_path = f"{wx_image_dir}/{filename}"
    device_path_wc = f"{wx_image_dir_wc}/{filename}"
    # 构建adb shell命令（指定设备） 
    adb_command = f"bash -l -c 'adb -s {device_serial} push {local_path} {device_path}' "
    adb_command_wc=f"bash -l -c 'adb -s {device_serial} push {local_path} {device_path_wc}' "
    # 执行命令
    output, error = exec_cmd_by_ssh(device_ip, port, username, password, adb_command)
    
    # 检查命令是否成功执行
    if error and "No such file or directory" in error:
        print(f"Failed to puss file: {error}")
        print('尝试/WeChat路径')
        output, error = exec_cmd_by_ssh(device_ip, port, username, password, adb_command_wc)
        return local_path
    elif error:
        print(f"Warning during puss file: {error}")
    else:
        print(f"File pushed successfully from {local_path} to {device_path}")
        print(f"Command output: {output}")
        return local_path