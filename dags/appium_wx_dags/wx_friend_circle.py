from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from utils.appium.wx_appium import search_contact_name
from utils.appium.wx_appium import WeChatOperator
import os

appium_server_info = Variable.get("WX_CONFIG_LIST", deserialize_json=True)

def test_search_contact_name(**context):
    search_contact_name(appium_server_url="42.193.193.179:6025", device_name='ZY22FX4H65', contact_name="1ucyEinstein", login_info={})

    

with DAG(
    dag_id='wx_friend_circle',
    default_args={'owner': 'yuchangongzhu'},
    schedule=timedelta(seconds=20),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信', "朋友圈"],
) as dag:

    wx_text_handler = PythonOperator(
        task_id='test_search_contact_name', 
        python_callable=test_search_contact_name,
        trigger_rule='none_failed_min_one_success',
        dag=dag
    )
