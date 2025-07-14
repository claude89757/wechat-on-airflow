from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from utils.appium.wx_appium import search_contact_name
from utils.appium.wx_appium import WeChatOperator
import os

appium_server_info = Variable.get("WX_CONFIG_LIST", deserialize_json=True)

def wx_friend_circle_analyze(**context):
    
    contact_name = context['dag_run'].conf.get('contact_name')
    search_contact_name(appium_server_url="http://42.193.193.179:6050", device_name='ZY22GVV5Z2', contact_name=contact_name, login_info={})

    

with DAG(
    dag_id='wx_friend_circle',
    default_args={'owner': 'yuchangongzhu'},
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信', "朋友圈"],
) as dag:

    wx_friend_circle_analyze = PythonOperator(
        task_id='wx_friend_circle_analyze', 
        python_callable=wx_friend_circle_analyze,
        trigger_rule='none_failed_min_one_success',
        dag=dag
    )
