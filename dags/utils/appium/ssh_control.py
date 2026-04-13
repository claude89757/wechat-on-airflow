import os
import re
import shlex
import time
import paramiko

def exec_cmd_by_ssh_with_status(host, port, username, password, cmd):
    """
    通过ssh远程执行命令
    :param host: 主机ip
    :param port: 主机ssh端口
    :param username: 主机用户名
    :param password: 主机密码
    :param cmd: 要执行的命令
    :return: 命令执行结果和退出码
    """
    ssh = None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print(f'正在连接{host}:{port}...')
        ssh.connect(hostname=host, port=port, username=username, password=password)
        _, stdout, stderr = ssh.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        print(f'命令{cmd}执行完成，返回结果')
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        if exit_status != 0 and not err:
            err = f"command exited with status {exit_status}"
        return out, err, exit_status

    except Exception as e:
        print(e)
        return None, str(e), None
    finally:
        # 保证ssh连接关闭
        if ssh is not None:
            ssh.close()


def exec_cmd_by_ssh(host, port, username, password, cmd):
    """
    兼容旧调用方的双返回值封装。
    """
    out, err, _ = exec_cmd_by_ssh_with_status(host, port, username, password, cmd)
    return out, err


def get_device_id_by_adb(host, port, username, password) -> list:
    '''
        通过adb命令获取设备号
        :param host: 主机地址
        :param port: 端口
        :param username: 用户名
        :param password: 密码
        :return: 设备号列表
    '''

    cmd = build_login_shell_adb_command('devices')
    # 执行adb命令
    out, _ = exec_cmd_by_ssh(host, port, username, password, cmd)
    if not out:
        return []

    # 解析adb命令的输出，获取设备号
    device_id_list = []
    for line in out.splitlines():
        if "List of devices attached" in line:
            continue
        # 如果该行有非空字符内容
        if line.strip():
            parts = re.split(r'\s+', line.strip())
            if len(parts) < 2 or parts[1] != "device":
                continue
            device_id = parts[0]
            print(f'设备号：{device_id}') 
            device_id_list.append(device_id)
    return device_id_list


def build_login_shell_adb_command(adb_command: str) -> str:
    """在登录 shell 中执行 adb，复用现有环境变量加载方式。"""
    return f"bash -l -c {shlex.quote(f'adb {adb_command}')}"


def parse_adb_devices_output(output: str, device_serial: str) -> bool:
    """判断目标设备是否以 device 状态出现在 adb devices 结果中。"""
    if not output:
        return False

    for line in output.splitlines():
        if "List of devices attached" in line:
            continue
        parts = re.split(r"\s+", line.strip())
        if len(parts) >= 2 and parts[0] == device_serial and parts[1] == "device":
            return True
    return False


def is_boot_completed_output(output: str) -> bool:
    """判断系统启动是否完成。"""
    return bool(output and output.strip() == "1")


def reboot_device_via_ssh_adb(device_ip, username, password, device_serial, port=22) -> bool:
    """通过 SSH 在宿主机上执行 adb reboot。"""
    adb_command = build_login_shell_adb_command(f"-s {device_serial} reboot")
    output, error, exit_status = exec_cmd_by_ssh_with_status(
        device_ip, port, username, password, adb_command
    )

    if exit_status is None:
        print(f"设备 {device_serial} 重启失败: {error}")
        return False

    if exit_status != 0:
        print(f"设备 {device_serial} 重启失败: {error}")
        return False

    if error:
        print(f"设备 {device_serial} 重启命令返回告警: {error}")

    print(f"设备 {device_serial} 已发送重启命令")
    if output:
        print(output)
    return True


def is_device_online_via_ssh_adb(device_ip, username, password, device_serial, port=22) -> bool:
    """检查设备是否重新出现在 adb devices 中。"""
    adb_command = build_login_shell_adb_command("devices")
    output, error, exit_status = exec_cmd_by_ssh_with_status(
        device_ip, port, username, password, adb_command
    )

    if exit_status is None:
        print(f"检查设备在线状态失败: {error}")
        return False

    if exit_status != 0:
        print(f"检查设备在线状态失败: {error}")
        return False

    if error:
        print(f"检查设备 {device_serial} 在线状态时有告警: {error}")

    return parse_adb_devices_output(output, device_serial)


def wait_for_device_boot_completed(device_ip, username, password, device_serial, port=22, timeout=300, interval=10) -> bool:
    """等待设备重新上线并完成系统启动。"""
    deadline = time.time() + timeout
    adb_boot_command = build_login_shell_adb_command(f"-s {device_serial} shell getprop sys.boot_completed")

    while time.time() < deadline:
        if not is_device_online_via_ssh_adb(device_ip, username, password, device_serial, port=port):
            print(f"设备 {device_serial} 尚未重新上线，{interval}s 后重试")
            time.sleep(interval)
            continue

        output, error, exit_status = exec_cmd_by_ssh_with_status(
            device_ip, port, username, password, adb_boot_command
        )
        if exit_status is None:
            print(f"获取设备启动状态失败: {error}")
            time.sleep(interval)
            continue

        if exit_status != 0:
            print(f"获取设备启动状态失败: {error}")
            time.sleep(interval)
            continue

        if error:
            print(f"获取设备 {device_serial} 启动状态时有告警: {error}")

        if is_boot_completed_output(output):
            print(f"设备 {device_serial} 已完成启动")
            return True

        print(f"设备 {device_serial} 已在线，但系统尚未完成启动，{interval}s 后重试")
        time.sleep(interval)

    print(f"等待设备 {device_serial} 启动完成超时，超时时间 {timeout}s")
    return False


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
    wx_image_dir_wc="/sdcard/Pictures/WeChat" #备用目录
    # 构建adb shell命令（指定设备） 
    adb_command = f"bash -l -c 'adb -s {device_serial} shell ls -t {wx_image_dir}' "
    adb_command_wc=f"bash -l -c 'adb -s {device_serial} shell ls -t {wx_image_dir_wc}' "
    output, error = exec_cmd_by_ssh(device_ip, port, username, password, adb_command)

    # 检查命令是否成功执行
    if error:
        print(f"Failed to get image path: {error}")
        output, error = exec_cmd_by_ssh(device_ip, port, username, password, adb_command_wc)
        return wx_image_dir_wc + "/" + output.split("\n")[0]
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