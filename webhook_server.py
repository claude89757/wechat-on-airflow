#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webhook服务器
功能：
1. 接收GitHub的webhook请求，自动更新代码
2. 接收微信消息回调，触发Airflow处理流程

使用方法：
1. 运行脚本: python webhook_server.py
2. 或后台运行: nohup python webhook_server.py > webhook.log 2>&1 &

配置说明：
1. GitHub webhook设置:
   - URL: http://服务器IP:5000/update
   - Content type: application/json
   
2. 微信消息回调设置:
   - URL: http://服务器IP:5000/wcf_callback
   - Content type: application/json
"""

from flask import Flask, request
import subprocess
import os
import logging
import requests
from datetime import datetime
import json

app = Flask(__name__)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='webhook.log'
)

# 项目目录路径
REPO_PATH = os.path.dirname(os.path.abspath(__file__))

# 添加Airflow API配置
AIRFLOW_API_URL = "http://129.204.143.82/api/v1/dags"
DAG_NAME = "wx_msg_watcher"  # 要触发的DAG名称

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

@app.route('/wcf_callback', methods=['POST'])
def handle_wcf_callback():
    """
    处理WCF回调请求
    接收回调数据并触发Airflow DAG
    """
    try:
        # 获取回调请求的数据
        callback_data = request.get_json()
        
        # 生成唯一的dag_run_id
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        dag_run_id = f"wcf_callback_{current_time}"
        
        # 准备Airflow API请求数据
        airflow_payload = {
            "conf": callback_data,  # 将回调数据作为conf参数传入
            "dag_run_id": dag_run_id,
            "logical_date": datetime.now().isoformat(),
            "note": "Triggered by WCF callback"
        }
        
        # 调用Airflow API触发DAG
        response = requests.post(
            f"{AIRFLOW_API_URL}/{DAG_NAME}/dagRuns",
            json=airflow_payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            logging.info(f'成功触发Airflow DAG: {DAG_NAME}')
            return {'message': 'DAG触发成功', 'dag_run_id': dag_run_id}, 200
        else:
            logging.error(f'触发Airflow DAG失败: {response.text}')
            return {'message': 'DAG触发失败', 'error': response.text}, 500
            
    except Exception as e:
        logging.error(f'处理WCF回调失败: {str(e)}')
        return {'message': '处理失败', 'error': str(e)}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 
