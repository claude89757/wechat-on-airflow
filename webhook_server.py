#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Webhook 自动部署脚本
功能：接收 GitHub 的 webhook 请求，自动更新代码
使用方法：
1. 运行脚本: python webhook_server.py
2. 或后台运行: nohup python webhook_server.py > webhook.log 2>&1 &
3. 在 GitHub 仓库设置 webhook:
   - URL: http://服务器IP:5000/update
   - Content type: application/json
"""

from flask import Flask
import subprocess
import os
import logging

app = Flask(__name__)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='webhook.log'
)

# 项目目录路径
REPO_PATH = os.path.dirname(os.path.abspath(__file__))

@app.route('/update', methods=['POST'])
def update_code():
    """
    处理代码更新请求
    接收 GitHub webhook POST 请求，执行 git fetch 和 reset 命令更新代码
    """
    try:
        # 切换到仓库目录
        os.chdir(REPO_PATH)
        
        # 执行git命令
        subprocess.run(['git', 'fetch', '--all'], check=True)
        subprocess.run(['git', 'reset', '--hard', 'origin/main'], check=True)
        
        logging.info('代码更新成功')
        return '更新成功', 200
    except Exception as e:
        logging.error(f'代码更新失败: {str(e)}')
        return '更新失败', 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 
