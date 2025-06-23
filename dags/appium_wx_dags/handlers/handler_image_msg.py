# airflow库
from airflow.models import Variable

# 自定义库
from utils.dify_sdk import DifyAgent
from utils.appium.wx_appium import download_file_via_sftp


def handle_image_messages(**context):
    """处理图片消息"""
    print(f"[HANDLE] 处理图片消息")
    try:
        appium_server_info = context['wx_config']
        print(f"[HANDLE] 获取Appium服务器信息: {appium_server_info}")
    except KeyError:
        print(f"[HANDLE] 获取Appium服务器信息失败: 未在 context 中找到 'wx_config'")
        return {}

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']

    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key='image_msg')
    print(f"[HANDLE] 获取XCOM: {recent_new_msg}")
    
    # 发送消息
    for contact_name, messages in recent_new_msg.items():
        image_url = ""
        for message in messages:
            if message['msg_type'] == 'image':
                image_url = message['msg'].split(":")[-1].strip()
                break
        print(f"[HANDLE] 图片路径: {image_url}")

        # appium服务器上拉取图片
        device_ip = login_info["device_ip"]
        username = login_info["username"]
        password = login_info["password"]
        port = login_info["port"]
        # 和appium服务器一样的路径
        download_file_via_sftp(device_ip, username, password, image_url, image_url, port=port)
        print(f"[HANDLE] 下载图片到本地: {image_url}")

        # 创建DifyAgent
        dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_api_url)

        # 获取会话ID
        dify_user_id = f"{wx_name}_{contact_name}"
        # 上传图片到Dify
        online_img_info = dify_agent.upload_file(image_url, dify_user_id)
        print(f"[HANDLE] 上传图片到Dify成功: {online_img_info}")

        # 这里不发起聊天消息,缓存到Airflow的变量中,等待文字消息来触发
        Variable.set(f"{dify_user_id}_online_img_info", online_img_info, serialize_json=True)
        

        # 以下是发送图片消息的逻辑，目前图片消息是缓存，等待文字触发后回复

        # 上传至appium服务器
        # upload_file_to_device_via_sftp(device_ip, username, password, image_url, image_url, port=port)
        # push_image_to_device(device_ip, username, password, device_name,image_url, image_url, port=port)
        # 发送图片到微信
        # send_top_n_image_or_video_msg_by_appium(appium_url, device_name, contact_name, top_n=1)

    return recent_new_msg
