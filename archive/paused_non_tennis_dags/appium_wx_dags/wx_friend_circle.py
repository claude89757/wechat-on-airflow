from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable,DagModel
from utils.appium.wx_appium import search_contact_name
from utils.appium.wx_appium import WeChatOperator
from appium_wx_dags.savers.saver_friend_circle_info import save_friend_circle_to_db
import os
import time
import json

appium_server_info = Variable.get("WX_CONFIG_LIST", deserialize_json=True)
def wx_friend_circle_analyze(**context):
    wx_name = context['dag_run'].conf.get('wx_name')
    contact_name = context['dag_run'].conf.get('contact_name')
    for i in appium_server_info:
        if i['wx_name']==wx_name:
            appium_server_url=i['appium_url']
            device_name=i['device_name']
            dag_id=i['dag_id']
            wx_user_id=i['wx_user_id']
    dag_model = DagModel.get_dagmodel(dag_id)
    # 暂停 AI回复DAG
    dag_model.set_is_paused(is_paused=True)
    print('已暂停AI回复的dag')
    time.sleep(5)
    

    # 保存朋友圈分析结果到数据库
    try:
        full_answer,metadata=search_contact_name(appium_server_url=appium_server_url, device_name=device_name, contact_name=contact_name, login_info={})
        print(f"保存朋友圈分析结果: {full_answer}")
        # 解析JSON字符串（如果full_answer是字符串）
        if isinstance(full_answer, str):
            analysis_data = json.loads(full_answer)
        else:
            analysis_data = full_answer
            
        # 保存到数据库
        save_friend_circle_to_db(
            wx_user_id=wx_user_id,
            wxid=contact_name,  # 使用联系人名称作为wxid（实际应用中应获取真实wxid）
            nickname=contact_name,  # 使用联系人名称作为昵称
            analysis_data=analysis_data
        )
        print(f"朋友圈分析结果保存成功")
    except Exception as e:
        print(f"保存朋友圈分析结果失败: {e}")
        
    # 取消暂停 DAG
    dag_model.set_is_paused(is_paused=False)

with DAG(
    dag_id='wx_friend_circle',
    default_args={'owner': 'yuchangongzhu'},
    start_date=datetime(2025, 4, 22),
    max_active_runs=5,
    catchup=False,
    tags=['个人微信', "朋友圈"],
) as dag:

    wx_friend_circle_analyze = PythonOperator(
        task_id='wx_friend_circle_analyze', 
        python_callable=wx_friend_circle_analyze,
        trigger_rule='none_failed_min_one_success',
        dag=dag,
        retries=3,
        retry_delay=timedelta(seconds=10)
    )
