#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from utils.redis import airflow_redis

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'demo_redis_operations',
    default_args=default_args,
    description='演示Redis基本操作的DAG',
    schedule_interval=timedelta(days=1),
    catchup=False
)

def set_redis_value(**context):
    """向Redis中写入数据"""
    # 写入字符串
    airflow_redis.set('demo_string', 'Hello from Airflow!')
    
    # 写入哈希表
    airflow_redis.hset('demo_hash', 'name', 'Airflow')
    airflow_redis.hset('demo_hash', 'version', '2.7.1')
    
    # 写入列表
    airflow_redis.lpush('demo_list', 'item1', 'item2', 'item3')
    
    print("数据已成功写入Redis")

def get_redis_value(**context):
    """从Redis中读取数据"""
    # 读取字符串
    string_value = airflow_redis.get('demo_string')
    print(f"字符串值: {string_value}")
    
    # 读取哈希表
    hash_value = airflow_redis.hgetall('demo_hash')
    print(f"哈希表值: {hash_value}")
    
    # 读取列表
    list_values = airflow_redis.lrange('demo_list', 0, -1)
    print(f"列表值: {list_values}")

def clean_redis_data(**context):
    """清理示例数据"""
    airflow_redis.delete('demo_string', 'demo_hash', 'demo_list')
    print("Redis数据已清理")

# 定义任务
t1 = PythonOperator(
    task_id='set_redis_value',
    python_callable=set_redis_value,
    dag=dag,
)

t2 = PythonOperator(
    task_id='get_redis_value',
    python_callable=get_redis_value,
    dag=dag,
)

t3 = PythonOperator(
    task_id='clean_redis_data',
    python_callable=clean_redis_data,
    dag=dag,
)

# 设置任务依赖
t1 >> t2 >> t3
