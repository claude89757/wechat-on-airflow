from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable,DagModel
from utils.appium.wx_appium import search_contact_name
from utils.appium.wx_appium import WeChatOperator
import os
import time

appium_server_info = Variable.get("WX_CONFIG_LIST", deserialize_json=True)
def wx_friend_circle_analyze(**context):
    wx_name = context['dag_run'].conf.get('wx_name')
    contact_name = context['dag_run'].conf.get('contact_name')
    for i in appium_server_info:
        if i['wx_name']==wx_name:
            appium_server_url=i['appium_url']
            device_name=i['device_name']
            dag_id=i['dag_id']
    dag_model = DagModel.get_dagmodel(dag_id)
    # 暂停 AI回复DAG
    dag_model.set_is_paused(is_paused=True)
    print('已暂停AI回复的dag')
    time.sleep(5)
    search_contact_name(appium_server_url=appium_server_url, device_name=device_name, contact_name=contact_name, login_info={})
    # 取消暂停 DAG
    dag_model.set_is_paused(is_paused=False)
    

    


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
