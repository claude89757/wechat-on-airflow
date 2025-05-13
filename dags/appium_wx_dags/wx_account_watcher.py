# 标准库导入
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.models.variable import Variable
from airflow.operators.python import PythonOperator

from utils.appium.ssh_control import get_device_id_by_adb
from utils.appium.wx_appium import get_wx_account_info_by_appium
from appium_wx_dags.common.mysql_tools import init_wx_chat_records_table

DAG_ID = "appium_wx_account_watcher"

def check_wx_account_info(**context):
    """
        检查微信账号信息
    """
    print("开始检查微信账号信息...")
    # 获取当前已缓存的用户信息
    wx_account_list = Variable.get("WX_ACCOUNT_LIST", default_var=[], deserialize_json=True)
    print(f"当前已缓存的用户信息: {len(wx_account_list)}")

    # 获取Appium服务地址
    appium_server_url_list = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)

    # 获取已缓存微信账号的id
    wx_account_vxid_list = [wx_account['wxid'] for wx_account in wx_account_list]

    # 假设所有用户都不在线
    for wx_account in wx_account_list: wx_account['is_online'] = False

    # 巡检Appium Server上的微信账号
    for appium_server in appium_server_url_list:

        appium_url = appium_server['appium_url']
        login_info = appium_server['login_info']

        # 提取IP或者域名部分
        host = appium_url.split('//')[-1].split(':')[0]

        # 获取所有连接设备
        device_list = get_device_id_by_adb(host=host, port=login_info['port'], username=login_info['username'], password=login_info['password'])

        # 遍历所有设备，检查账号信息
        for device_id in device_list:
            wx_account_info = get_wx_account_info_by_appium(appium_server_url=appium_url, device_name=device_id, login_info=login_info)

            # 提取微信名称和id
            wx_name = wx_account_info['wx_name']
            wxid = wx_account_info['wxid']
            print(f"[INFO] 设备{device_id}的微信账号:{wx_name}，微信id:{wxid}")

            if wxid not in wx_account_vxid_list:
                # 新增用户信息
                wx_account_list.append({
                    "name": wx_name,
                    "wxid": wxid,
                    "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "is_online": True,
                    "mobile": '13888888888' # TODO: 这里应该从微信服务器获取手机号
                })

                # 初始化新用户的聊天记录表
                try:
                    init_wx_chat_records_table(wxid)
                except Exception as error:
                    print(f"[WATCHER] 初始化新用户聊天记录表失败: {error}")

            else:
                # 更新缓存的用户信息
                for wx_account in wx_account_list:
                    if wx_account['wxid'] == wxid:
                        wx_account['name'] = wx_name
                        wx_account['update_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        wx_account['is_online'] = True
                        break

    # 更新缓存的用户信息
    Variable.set("WX_ACCOUNT_LIST", wx_account_list, serialize_json=True)


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