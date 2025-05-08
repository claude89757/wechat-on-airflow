# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

from utils.appium.ssh_appium_control import get_device_id_by_adb
from utils.appium.wx_appium import get_wx_account_info_by_appium

DAG_ID = "appium_wx_account_watcher"

def check_wx_account_info(**context):
    """
        检查微信账号信息
    """
    print("开始检查微信账号信息...")
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息: {len(wx_account_list)}")

    #########################以上似乎不需要了###################################################################

    # 获取Appium服务地址
    appium_server_url_list = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)

    # 巡检Appium Server上的微信账号
    all_wx_account = []
    for appium_server in appium_server_url_list:

        appium_url = appium_server['appium_url']
        login_info = appium_server['login_info']

        # 获取所有连接设备
        device_list = get_device_id_by_adb(host=appium_url, port=login_info['port'], username=login_info['username'], password=login_info['password'])

        wx_account_list = []
        # 遍历所有设备，检查账号信息
        for device_id in device_list:
            wx_name, wxid= get_wx_account_info_by_appium(appium_server_url=appium_url, device_name=device_id, login_info=login_info)
            print(f"[INFO] 设备{device_id}的微信账号为{wx_name}，微信id为{wxid}")

            # 缓存账号信息
            wx_account_list.append({
                "device_id": device_id,
                "wx_name": wx_name,
                "wxid": wxid
            })

        all_wx_account.append({appium_url: wx_account_list})
    # 更新缓存的用户信息
    Variable.set("WX_ACCOUNT_LIST", all_wx_account, serialize_json=True)


with DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'airflow'},
    start_date=datetime(2025, 5, 8),
    max_active_runs=1,
    schedule_interval=timedelta(minutes=2),
    dagrun_timeout=timedelta(minutes=1),
    catchup=False,
    tags=['个人微信'],
    description='使用appium监控个人微信账号'
    ) as dag:

    wx_account_watcher = PythonOperator(
        task_id="check_wx_account_info",
        python_callable=check_wx_account_info,
        provide_context=True,
    )