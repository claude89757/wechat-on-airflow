from airflow.models import Variable

from appium_wx_dags.handlers.handler_text_msg import handle_msg_by_ai
from utils.appium.wx_appium import send_wx_msg_by_appium

'''
    处理语音消息的模块逻辑与处理文字消息的模块逻辑基本一致，appium直接通过语音转文字的形式保存信息
'''

def handle_voice_messages(**context):
    """处理语音消息"""
    print(f"[HANDLE] 处理语音消息")
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
    recent_new_msg = context['ti'].xcom_pull(key='voice_msg')
    print(f"[HANDLE] 获取XCOM: {recent_new_msg}")

    # 检查是否有消息任务，有则处理
    if recent_new_msg:
        print(f"[HANDLE] 获取XCOM: {recent_new_msg}")
        # 发送消息
        for contact_name, messages in recent_new_msg.items():
            msg_list = []
            for message in messages:
                # 如果message['msg']中包含':'，则取最后一个':'后面的内容作为消息内容，否则为空
                if ':' in message['msg']:
                    msg_list.append(message['msg'].split(':')[-1])
                else:
                    msg_list.append('')
            msg = "\n".join(msg_list)

            # AI 回复
            response_msg_list = handle_msg_by_ai(dify_api_url, dify_api_key, wx_name, contact_name, msg)

            if response_msg_list:
                send_wx_msg_by_appium(appium_url, device_name, contact_name, response_msg_list)
            else:
                print(f"[HANDLE] 没有AI回复")
    else:
        print(f"[HANDLE] 没有语音消息处理任务")

    return recent_new_msg
