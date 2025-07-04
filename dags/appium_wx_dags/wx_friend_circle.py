from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
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
    
    def get_appium_server_info(**context):
        """获取Appium服务器信息"""
        try:
            appium_server_info = context['params'].get('wx_config', {})
            print(f"[WATCHER] 获取Appium服务器信息: {appium_server_info}")
            return appium_server_info
        except Exception as e:
            print(f"[WATCHER] 获取Appium服务器信息失败: {str(e)}")
            return {}
    
    get_server_info = PythonOperator(
        task_id='get_server_info',
        python_callable=get_appium_server_info,
        provide_context=True,
        dag=dag
    )
    
    # 定义操作参数
    def prepare_search_params(**context):
        """准备搜索联系人所需的参数"""
        appium_server_info = context['ti'].xcom_pull(task_ids='get_server_info')
        if not appium_server_info:
            raise ValueError("未能获取Appium服务器信息")
            
        op_kwargs = {
            'wx_name': appium_server_info.get('wx_name'),
            'device_name': appium_server_info.get('device_name'),
            'appium_url': appium_server_info.get('appium_url'),
            'dify_api_url': appium_server_info.get('dify_api_url'),
            'dify_api_key': appium_server_info.get('dify_api_key'),
            'login_info': appium_server_info.get('login_info')
        }
        return op_kwargs
    
    prepare_params = PythonOperator(
        task_id='prepare_params',
        python_callable=prepare_search_params,
        provide_context=True,
        dag=dag
    )
    
    # 搜索联系人
    wx_text_handler = PythonOperator(
        task_id='search_contact_name', 
        python_callable=search_contact_name, 
        op_kwargs={"contact_params": "{{ ti.xcom_pull(task_ids='prepare_params') }}"},
        trigger_rule='none_failed_min_one_success',
        dag=dag
    )
    
    # 设置任务依赖关系
    get_server_info >> prepare_params >> wx_text_handler
