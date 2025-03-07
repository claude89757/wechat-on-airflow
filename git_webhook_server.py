#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git Webhook 微服务 (Flask版)
=========================

功能：
- 接收GitHub的webhook请求，自动更新代码

使用方法：
1. 安装依赖:
   pip install flask

2. 运行服务器:
   python git_webhook_server.py

3. 后台运行服务器:
   nohup python git_webhook_server.py > git_webhook.log 2>&1 &

4. 查看后台运行状态:
   ps aux | grep git_webhook_server.py

5. 停止后台运行的服务器:
   pkill -f git_webhook_server.py
"""

import os
import logging
from datetime import datetime
from flask import Flask, request, Response

# 配置
REPO_PATH = os.path.dirname(os.path.abspath(__file__))
PORT = 5000
LOG_FILE = os.path.join(REPO_PATH, "git_webhook.log")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()  # 同时输出到控制台
    ]
)
logger = logging.getLogger("git_webhook")

app = Flask(__name__)

def log_message(message):
    """记录日志消息到文件和控制台"""
    logger.info(message)

def run_command(command):
    """运行命令并返回输出"""
    cmd_str = ' '.join(command)
    
    try:
        # 使用 os.popen 执行命令
        cmd = f"cd {REPO_PATH} && {cmd_str}"
        log_message(f"执行命令: {cmd}")
        output = os.popen(cmd).read()
        if not output:
            log_message("命令执行成功，但没有输出")
        return output.strip()
    except Exception as e:
        log_message(f"命令执行失败: {cmd_str}")
        log_message(f"错误: {str(e)}")
        raise

@app.route('/update', methods=['POST'])
def update_repo():
    try:
        log_message("接收到GitHub webhook请求，开始更新代码...")
        
        # 执行git命令
        run_command(['git', 'fetch', '--all'])
        run_command(['git', 'reset', '--hard', 'origin/main'])
        
        # 获取最新提交信息 - 一次性获取所需信息
        commit_hash = run_command(['git', 'rev-parse', '--short', 'HEAD'])
        commit_msg = run_command(['git', 'show', '-s', '--format=%s'])
        
        # 返回成功信息
        update_info = f"更新成功！最新提交: {commit_hash} {commit_msg}"
        log_message(update_info)
        return Response(update_info, status=200, mimetype='text/plain; charset=utf-8')
        
    except Exception as e:
        error_message = f"更新失败: {str(e)}"
        log_message(error_message)
        return Response(error_message, status=500, mimetype='text/plain; charset=utf-8')

@app.route('/', methods=['GET'])
def home():
    return Response("Git Webhook 服务器正在运行", status=200, mimetype='text/plain; charset=utf-8')

if __name__ == "__main__":
    log_message(f"Git Webhook 服务器启动，监听端口 {PORT}...")
    log_message("等待 GitHub webhook 请求...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
