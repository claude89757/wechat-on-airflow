#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optimized Webhook Server using FastAPI
======================================

功能：
1. 接收GitHub的webhook请求，自动更新代码
2. 接收微信消息回调，触发Airflow处理流程

优化内容：
- 使用FastAPI提升并发性能
- 实现异步处理，提高API调用成功率
- 单一文件结构，简化项目架构
- 实现API限速配置
- 清晰的导入和代码结构

使用方法：
1. 安装依赖:
   pip install -r requirements.txt

2. 创建 .env 文件并配置环境变量:
   AIRFLOW_BASE_URL=<Your Airflow Base URL>
   AIRFLOW_USERNAME=<Your Airflow Username>
   AIRFLOW_PASSWORD=<Your Airflow Password>
   RATE_LIMIT_UPDATE=<Rate limit for /update endpoint, e.g., "10/minute">
   RATE_LIMIT_WCF=<Rate limit for /wcf_callback endpoint, e.g., "100/minute">

3. 运行服务器:
   使用 Uvicorn 启动:
   uvicorn webhook_server:app --host 0.0.0.0 --port 5000 --workers 2

   或者使用 Gunicorn 提高并发性能:
   gunicorn webhook_server:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:5000

   或者后台运行 Gunicorn:
   nohup gunicorn webhook_server:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:5000 > webhook.log 2>&1 &
"""

import os
import re
import subprocess
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

import asyncio
import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import PlainTextResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

# =====================
# Configuration
# =====================

# Load environment variables from .env file
load_dotenv()

# Airflow Configuration
AIRFLOW_BASE_URL = os.getenv("AIRFLOW_BASE_URL")
AIRFLOW_USERNAME = os.getenv("AIRFLOW_USERNAME")
AIRFLOW_PASSWORD = os.getenv("AIRFLOW_PASSWORD")

# Rate Limiting Configuration
RATE_LIMIT_UPDATE = os.getenv("RATE_LIMIT_UPDATE", "50/minute")
RATE_LIMIT_WCF = os.getenv("RATE_LIMIT_WCF", "100/minute")

# Repository Path
REPO_PATH = os.path.dirname(os.path.abspath(__file__))

# =====================
# Logging Configuration
# =====================

def setup_logging():
    logger = logging.getLogger("webhook_server")
    logger.setLevel(logging.INFO)

    # 将日志输出到标准输出，这样可以通过docker logs查看
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

logger = setup_logging()

# =====================
# FastAPI App Initialization
# =====================

app = FastAPI(title="Optimized Webhook Server")

# Initialize Limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["200/day", "50/hour"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# =====================
# Routes
# =====================

@app.post("/update", response_class=PlainTextResponse)
@limiter.limit(RATE_LIMIT_UPDATE)
async def update_code(request: Request):
    """
    处理GitHub webhook请求，执行代码更新
    """
    try:
        logger.info('接收到GitHub webhook请求')
        
        # 使用loop.run_in_executor替代asyncio.to_thread
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, execute_git_commands)

        logger.info('代码更新成功')
        return PlainTextResponse(content="更新成功", status_code=status.HTTP_200_OK)
    except subprocess.CalledProcessError as git_error:
        logger.error(f'Git命令执行失败: {git_error}')
        return PlainTextResponse(content="Git命令执行失败", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.error(f'代码更新失败: {e}')
        return PlainTextResponse(content="更新失败", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

@app.post("/wcf_callback")
@limiter.limit(RATE_LIMIT_WCF)
async def handle_wcf_callback(request: Request):
    """
    处理WCF回调请求，触发Airflow DAG
    """
    try:
        callback_data = await request.json()
        if not callback_data:
            logger.warning('没有收到有效的回调数据')
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"message": "无效的数据"})

        logger.info(f'接收到WCF回调数据: {callback_data}')

        # Trigger Airflow DAG asynchronously
        dag_run_id = await trigger_airflow_dag(callback_data)

        logger.info(f'Airflow DAG触发成功, dag_run_id: {dag_run_id}')
        return JSONResponse(status_code=status.HTTP_200_OK, content={"message": "DAG触发成功", "dag_run_id": dag_run_id})

    except httpx.RequestError as req_err:
        logger.error(f'调用Airflow API时发生请求异常: {req_err}')
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": "Airflow API请求失败", "error": str(req_err)})
    except Exception as e:
        logger.error(f'处理WCF回调失败: {e}')
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": "处理失败", "error": str(e)})

@app.get("/health")
async def health_check():
    """
    健康检查端点
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "healthy", "timestamp": datetime.now().isoformat()}
    )

# =====================
# Helper Functions
# =====================

def execute_git_commands():
    """
    执行git fetch和git reset命令以更新代码
    """
    try:
        logger.info('开始执行git fetch --all')
        subprocess.run(['git', 'fetch', '--all'], check=True, cwd=REPO_PATH)
        logger.info('git fetch --all 成功')

        logger.info('开始执行git reset --hard origin/main')
        subprocess.run(['git', 'reset', '--hard', 'origin/main'], check=True, cwd=REPO_PATH)
        logger.info('git reset --hard origin/main 成功')
    except subprocess.CalledProcessError as e:
        logger.error(f'Git命令执行失败: {e}')
        raise

async def trigger_airflow_dag(callback_data):
    """
    异步触发Airflow DAG
    """
    try:
        # todo(@claude89757): 这里可以考虑增加消息聚合的逻辑，等待一段时间，多个消息合并为一个, 触发一次dag
        # 根据Airflow的DAG run ID命名规范, 删除所有非字母数字字符
        roomid = re.sub(r'[^a-zA-Z0-9]', '', callback_data.get("roomid", ""))
        msg_id = re.sub(r'[^a-zA-Z0-9]', '', callback_data.get("id", ""))
        dag_run_id = f"{roomid}_{msg_id}"
        airflow_payload = {
            "conf": callback_data,
            "dag_run_id": dag_run_id,
            "note": "Triggered by WCF callback"
        }

        logger.info(f'准备触发Airflow DAG: wx_msg_watcher, dag_run_id: {dag_run_id}')

        async with httpx.AsyncClient(auth=(AIRFLOW_USERNAME, AIRFLOW_PASSWORD), timeout=10) as client:
            response = await client.post(
                f"{AIRFLOW_BASE_URL}/api/v1/dags/wx_msg_watcher/dagRuns",
                json=airflow_payload,
                headers={'Content-Type': 'application/json'}
            )

        if response.status_code in [200, 201]:
            logger.info(f'成功触发Airflow DAG: wx_msg_watcher, dag_run_id: {dag_run_id}')
            return dag_run_id
        else:
            logger.error(f'触发Airflow DAG失败: {response.status_code} - {response.text}')
            response.raise_for_status()

    except httpx.RequestError as req_err:
        logger.error(f'调用Airflow API时发生请求异常: {req_err}')
        raise
    except Exception as e:
        logger.error(f'触发Airflow DAG任务失败: {e}')
        raise

# =====================
# Global Exception Handlers
# =====================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    logger.warning(f'未找到的路由: {request.url.path}')
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"error": "Not found"})

@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.error(f'服务器内部错误: {exc}')
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error"})

# =====================
# Main Entry
# =====================

# Note: For production, use a WSGI server like Uvicorn or Gunicorn to handle concurrency
