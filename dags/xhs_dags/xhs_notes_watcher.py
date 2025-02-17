#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

from utils.xhs_appium import XHSOperator


def collect_xhs_notes(**context) -> None:
    """
    收集小红书笔记
    
    从小红书搜索指定关键词的笔记并缓存到Airflow变量中。
    
    Args:
        **context: Airflow上下文参数字典
    
    Returns:
        None
    """
    # 获取关键词，默认为"AI客服"
    keyword = (context['dag_run'].conf.get('keyword', '网球') 
              if context['dag_run'].conf 
              else '网球')
    
    # 获取最大收集笔记数，默认为5
    max_notes = (context['dag_run'].conf.get('max_notes', 5)
                if context['dag_run'].conf
                else 5)
    
    # 获取Appium服务器URL
    appium_server_url = Variable.get("APPIUM_SERVER_URL", "http://localhost:4723")
    
    print(f"开始收集关键词 '{keyword}' 的小红书笔记...")
    
    try:
        # 初始化小红书操作器
        xhs = XHSOperator(appium_server_url=appium_server_url, force_app_launch=True)
        
        # 检查是否在首页
        if not xhs.is_at_xhs_home_page():
            xhs.return_to_home_page()
        
        # 收集笔记
        notes = xhs.collect_notes_by_keyword(
            keyword=keyword,
            max_notes=max_notes
        )
        
        if not notes:
            print(f"未找到关于 '{keyword}' 的笔记")
            return
            
        # 打印收集结果
        print("\n收集完成!")
        print(f"共收集到 {len(notes)} 条笔记:")
        for note in notes:
            print(note)

        # 缓存数据到Airflow变量
        date_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        cache_key = f"XHS_NOTES_{keyword}"
        Variable.set(cache_key, notes, serialize_json=True, description=f"小红书笔记缓存: {keyword} at {date_str}")
            
    except Exception as e:
        error_msg = f"收集小红书笔记失败: {str(e)}"
        print(error_msg)
        raise
    finally:
        # 确保关闭小红书操作器
        if 'xhs' in locals():
            xhs.close()


# DAG 定义
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
    'xhs_notes_watcher',
    default_args=default_args,
    description='定时收集小红书笔记',
    schedule_interval='0 10,15,20 * * *',  # 每天10点、15点和20点执行
    catchup=False,
)

collect_notes_task = PythonOperator(
    task_id='collect_xhs_notes',
    python_callable=collect_xhs_notes,
    provide_context=True,
    dag=dag,
)
