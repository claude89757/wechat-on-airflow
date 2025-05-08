import re

from utils.appium.ssh_control import exec_cmd_by_ssh

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
    out = exec_cmd_by_ssh(host, port, username, password, cmd)

    # 解析adb命令的输出，获取设备号
    device_id_list = []
    for line in out.splitlines()[1:]:
        # 如果该行有非空字符内容
        if line.strip():
            device_id = re.split(r'\s+', line)[0]
            print(f'设备号：{device_id}') 
            device_id_list.append(device_id)
    return device_id_list
