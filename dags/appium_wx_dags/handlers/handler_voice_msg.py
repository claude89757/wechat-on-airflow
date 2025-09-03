from airflow.models import Variable

from appium_wx_dags.handlers.handler_text_msg import handle_msg_by_ai
from utils.appium.wx_appium import send_wx_msg_by_appium
from appium_wx_dags.common.wx_tools import build_token_usage_data
from appium_wx_dags.common.mysql_tools import save_token_usage_to_db

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
    wx_user_id = appium_server_info['wx_user_id']
    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']
    login_info = appium_server_info['login_info']
    response_msg={}
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
            response_msg_list,metadata = handle_msg_by_ai(dify_api_url, dify_api_key, wx_name, contact_name, msg)
            response_msg[contact_name] = response_msg_list
            if response_msg_list:
                send_wx_msg_by_appium(appium_url, device_name, contact_name, response_msg_list)
            else:
                print(f"[HANDLE] 没有AI回复")
            try:
                token_usage_data = build_token_usage_data(metadata, wx_user_id, contact_name)
                # 提取token信息
                
                save_token_usage_to_db(token_usage_data, wx_user_id)
                print(f"已保存联系人 {contact_name} 的token用量")
            except Exception as e:
                print(f"保存token用量失败: {e}")
    else:
        print(f"[HANDLE] 没有语音消息处理任务")
    context['ti'].xcom_push(key='voice_msg_response', value=response_msg)
    context['task_instance'].xcom_push(key='chat_summary_token_usage_data', value=metadata.get("metadata", {}))
    print(f"[HANDLE] 处理结果保存到XCOM: {response_msg}")
    return recent_new_msg
