#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WCF回调监听服务

这个DAG创建一个长期运行的Flask服务器，用于监听和记录回调请求。
服务器每天重启一次，并且同一时间只允许一个实例运行。

特点:
- 提供 /callback POST接口
- 自动记录所有请求
- 支持优雅关闭
- 每日重启

Author: Your Name
Date: 2024-01
"""

# 标准库导入
import signal
import threading
from datetime import datetime, timedelta

# 第三方库导入
from flask import Flask, request
from werkzeug.serving import make_server

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator

# 创建Flask应用
app = Flask(__name__)

# 定义回调接口
@app.route('/callback', methods=['POST'])
def callback():
    """
    处理回调请求的接口
    
    接收POST请求，打印请求内容
    
    Returns:
        dict: 包含处理状态的响应
    """
    data = request.get_json()
    print(f"收到回调请求: {data}")
    return {"status": "success"}

class FlaskServer:
    """
    Flask服务器包装类
    
    提供服务器的启动和关闭功能
    """
    def __init__(self):
        self.server = None

    def run_server(self):
        """启动服务器"""
        self.server = make_server('0.0.0.0', 5000, app)
        print("API服务器启动在端口5000...")
        self.server.serve_forever()

    def shutdown_server(self):
        """优雅关闭服务器"""
        if self.server:
            print("正在关闭API服务器...")
            self.server.shutdown()

flask_server = FlaskServer()

def start_flask_server():
    """
    DAG任务主函数
    
    启动Flask服务器并保持运行，直到收到终止信号
    包含信号处理逻辑，确保服务器能够优雅关闭
    """
    def signal_handler(signum, frame):
        print(f"收到信号 {signum}，准备关闭服务器...")
        flask_server.shutdown_server()
        
    # 注册信号处理器
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    server_thread = threading.Thread(target=flask_server.run_server)
    server_thread.daemon = True
    server_thread.start()
    
    try:
        # 保持任务运行直到DAG被重新调度
        while True:
            import time
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print("收到退出信号，正在关闭服务器...")
        flask_server.shutdown_server()

# 定义DAG的默认参数
default_args = {
    'owner': 'claude89757',              # DAG所有者
    'depends_on_past': False,        # 不依赖于过去的运行
    'start_date': datetime(2024, 1, 1),  # DAG开始日期
    'email_on_failure': False,       # 失败时不发送邮件
    'email_on_retry': False,         # 重试时不发送邮件
    'retries': 1,                    # 失败时重试1次
    'retry_delay': timedelta(minutes=5),  # 重试间隔5分钟
}

# 创建DAG
dag = DAG(
    'WCF回调请求监控流程',
    default_args=default_args,
    description='用于监听回调API请求的DAG',
    schedule_interval='@daily',       # 每天运行一次
    catchup=False,                    # 不执行历史任务
    max_active_runs=1                 # 最多同时运行1个实例
)

# 创建任务
api_server_task = PythonOperator(
    task_id='run_api_server',
    python_callable=start_flask_server,
    dag=dag
)
