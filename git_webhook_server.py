#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git Webhook 微服务 (Flask版)
=========================

功能：
- 接收GitHub的webhook请求，自动更新代码
- 支持简单的安全验证

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
import subprocess
import hmac
import hashlib
from datetime import datetime
from flask import Flask, request, Response, abort

# 配置
REPO_PATH = os.path.dirname(os.path.abspath(__file__))
PORT = 5000
# 可选：设置 GitHub Webhook 密钥进行验证
# 如果不需要验证，设置为 None
SECRET_TOKEN = os.environ.get('WEBHOOK_SECRET', None)

app = Flask(__name__)

def log_message(message):
    """打印带时间戳的日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def run_command(command):
    """运行命令并返回输出"""
    try:
        result = subprocess.run(command, check=True, cwd=REPO_PATH, 
                               capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log_message(f"命令执行失败: {' '.join(command)}")
        log_message(f"错误输出: {e.stderr}")
        raise

def verify_signature(request_data, signature_header):
    """验证 GitHub webhook 签名"""
    if not SECRET_TOKEN:
        return True  # 如果没有设置密钥，跳过验证
        
    if not signature_header:
        return False
        
    # 获取签名
    sha_name, signature = signature_header.split('=')
    if sha_name != 'sha1':
        return False
        
    # 计算 HMAC
    mac = hmac.new(SECRET_TOKEN.encode(), msg=request_data, digestmod=hashlib.sha1)
    return hmac.compare_digest(mac.hexdigest(), signature)

@app.route('/update', methods=['POST'])
def update_repo():
    # 验证请求
    if SECRET_TOKEN:
        signature = request.headers.get('X-Hub-Signature')
        if not verify_signature(request.data, signature):
            log_message("签名验证失败，拒绝请求")
            abort(403)
    
    try:
        log_message("接收到GitHub webhook请求，开始更新代码...")
        
        # 执行git命令并捕获输出
        fetch_output = run_command(['git', 'fetch', '--all'])
        log_message(f"Git fetch 输出:\n{fetch_output}")
        
        reset_output = run_command(['git', 'reset', '--hard', 'origin/main'])
        log_message(f"Git reset 输出:\n{reset_output}")
        
        # 获取最新提交信息
        commit_info = run_command(['git', 'log', '-1', '--pretty=format:%h %s (%an)'])
        
        # 返回成功信息
        update_info = f"更新成功！\n最新提交: {commit_info}"
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
    if SECRET_TOKEN:
        log_message("已启用 Webhook 签名验证")
    else:
        log_message("警告: 未设置 Webhook 密钥，任何请求都将被接受")
    log_message("等待 GitHub webhook 请求...")
    app.run(host='0.0.0.0', port=PORT, debug=False)
