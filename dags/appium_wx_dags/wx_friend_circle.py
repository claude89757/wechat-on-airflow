from utils.appium.wx_appium import search_contact_name

with DAG(
    dag_id='appium_wx_msg_watcher',
    default_args={'owner': 'claude89757'},
    description='使用Appium SDK自动化微信操作',
    schedule=timedelta(seconds=20),
    start_date=datetime(2025, 4, 22),
    max_active_runs=1,
    catchup=False,
    tags=['个人微信'],
) as dag:

    try:
        # 从 op_kwargs 传入的参数会被放入 context 中
        appium_server_info = context['wx_config']
        print(f"[WATCHER] 获取Appium服务器信息: {appium_server_info}")
    except KeyError:
        print(f"[WATCHER] 获取Appium服务器信息失败: 未在 context 中找到 'wx_config'")

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']

    search_contact_name(appium_server_url=appium_url, device_name=device_name, contact_name='1ucyEinstein', login_info=login_info)
