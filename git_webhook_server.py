#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git Webhook 微服务
=================

功能：
- 接收GitHub的webhook请求，自动更新代码

使用方法：
1. 无需安装额外依赖，使用Python标准库

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
import http.server
import socketserver

# 配置
REPO_PATH = os.path.dirname(os.path.abspath(__file__))
PORT = 5000

class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/update":
            self._send_response(404, "未找到")
            return
            
        try:
            # 执行git命令
            self._run_git_update()
            
            # 获取最新提交信息
            commit_info = subprocess.run(
                ['git', 'log', '-1', '--pretty=format:%h %s (%an)'], 
                check=True, cwd=REPO_PATH, capture_output=True, text=True
            ).stdout
            
            # 返回成功信息
            update_info = f"更新成功！\n最新提交: {commit_info}"
            print(update_info)
            self._send_response(200, update_info)
            
        except Exception as e:
            error_message = f"更新失败: {str(e)}"
            print(error_message)
            self._send_response(500, error_message)
    
    def _run_git_update(self):
        """执行git更新命令"""
        subprocess.run(['git', 'fetch', '--all'], check=True, cwd=REPO_PATH)
        subprocess.run(['git', 'reset', '--hard', 'origin/main'], check=True, cwd=REPO_PATH)
    
    def _send_response(self, status_code, message):
        """发送HTTP响应"""
        self.send_response(status_code)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))

if __name__ == "__main__":
    print(f"Git Webhook 服务器启动，监听端口 {PORT}...")
    with socketserver.TCPServer(("", PORT), WebhookHandler) as httpd:
        print(f"等待 GitHub webhook 请求...")
        httpd.serve_forever()
