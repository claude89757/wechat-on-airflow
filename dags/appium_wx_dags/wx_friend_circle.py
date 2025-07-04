from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from utils.appium.wx_appium import search_contact_name

with DAG(
    dag_id='friend_circle',
    default_args={'owner': 'yuchangongzhu'},
    schedule=timedelta(seconds=20),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信', "朋友圈"],
) as dag:
    
    # 直接从 Variable 获取配置
    appium_server_info = Variable.get("wx_config", deserialize_json=True)
    
    # 定义操作参数
    op_kwargs = {
        'wx_name': appium_server_info.get('wx_name'),
        'device_name': appium_server_info.get('device_name'),
        'appium_url': appium_server_info.get('appium_url'),
        'dify_api_url': appium_server_info.get('dify_api_url'),
        'dify_api_key': appium_server_info.get('dify_api_key'),
        'login_info': appium_server_info.get('login_info')
    }
    
    # 搜索联系人
    wx_text_handler = PythonOperator(
        task_id='search_contact_name', 
        python_callable=search_contact_name, 
        op_kwargs=op_kwargs,
        trigger_rule='none_failed_min_one_success',
        dag=dag
    )
