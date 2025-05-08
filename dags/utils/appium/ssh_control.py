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
        _, stdout, _ = ssh.exec_command(cmd)
        print(f'命令{cmd}执行成功')
        out = stdout.read().decode()
        return out 

    except Exception as e:
        print(e)
        return None
    finally:
        # 保证ssh连接关闭
        ssh.close()