#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/1/13 10:00
@Author  : claude89757
@File    : db_cleanup.py
@Software: Cursor
"""

from datetime import timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.db_cleanup import run_cleanup
import pendulum


def cleanup_airflow_db():
    """
    使用 Airflow 的 run_cleanup 函数直接清理数据库。
    会删除 clean_before_date 之前的数据。
    """
    try:
        # 这里修改为 30 天，让脚本真正删除 30 天之前的数据。
        clean_before_date = pendulum.now("UTC") - timedelta(days=30)

        # 调用 run_cleanup
        run_cleanup(
            table_names=None,             # None 表示清理所有支持的表
            dry_run=False,                # 设置为 False 才会真正执行删除
            clean_before_timestamp=clean_before_date,
            verbose=True,                 # 输出详细信息
            confirm=False,                # 跳过执行前确认
            skip_archive=True,            # 是否跳过存档步骤，可根据需要设置
        )
    except Exception as e:
        print(f"Error during cleanup: {e}")


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'start_date': pendulum.datetime(2022, 1, 1, tz="UTC"),
}

dag = DAG(
    'airflow_db_cleanup',
    default_args=default_args,
    description='Clean up Airflow database',
    schedule_interval=timedelta(days=1),
    catchup=False,
    max_active_runs=1,
)

db_cleanup_task = PythonOperator(
    task_id='db_cleanup',
    python_callable=cleanup_airflow_db,
    dag=dag,
)