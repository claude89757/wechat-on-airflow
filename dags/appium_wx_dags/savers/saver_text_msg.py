import uuid
from datetime import datetime

from airflow.models import Variable

from appium_wx_dags.common.wx_tools import WX_MSG_TYPES
from appium_wx_dags.common.mysql_tools import save_data_to_db
from appium_wx_dags.common.timestamp_helper import convert_time_to_timestamp


def save_text_msg_to_db(**context):
    """保存文本消息到数据库"""
    print(f"[SAVE] 保存文本消息到数据库")

    try:
        wx_config = context['wx_config']
        print(f"[SAVE] 获取微信配置信息: {wx_config}")
    except KeyError:
        print(f"[SAVE] 获取微信配置信息失败: 未在 context 中找到 'wx_config'")
        return

    # 提交对方发送的信息
    recent_new_msg = context['ti'].xcom_pull(key='text_msg', task_ids='wx_watcher')
    for contact_name, messages in recent_new_msg.items():
        for message in messages:
            save_msg = {}
            save_msg['msg_id'] = str(uuid.uuid4())
            save_msg['content'] = message['msg']
            save_msg['msg_type'] = 1 # 文本消息
            save_msg['msg_type_name'] = WX_MSG_TYPES.get(save_msg['msg_type'], f"未知类型({save_msg['msg_type']})")
            save_msg['is_self'] = False # 是否自己发送的消息
            save_msg['is_group'] = False # 是否群消息
            save_msg['msg_timestamp'] = convert_time_to_timestamp(message['msg_time'])
            save_msg['msg_datetime'] = datetime.fromtimestamp(save_msg['msg_timestamp']).strftime('%Y-%m-%d %H:%M')
            save_msg['wx_user_name'] = wx_config['wx_name']
            save_msg['wx_user_id'] = wx_config['wx_user_id']
            save_msg['room_id'] = contact_name # 暂时用会话名称代替房间ID
            save_msg['room_name'] = contact_name
            save_msg['sender_id'] = message['sender'] # 发送者ID，暂时用发送者名称代替
            save_msg['sender_name'] = message['sender']
            save_msg['source_ip'] = ''

            print(f"[SAVE] 发送者: {save_msg['sender_name']}, 消息内容: {save_msg['content']},")
            save_data_to_db(save_msg)

    # 保存回复的信息
    response_msg = context['ti'].xcom_pull(key='text_msg_response', task_ids='wx_text_handler')
    for contact_name, msg_list in response_msg.items(): 
        for message in msg_list:
            save_msg = {}
            save_msg['msg_id'] = str(uuid.uuid4())
            save_msg['content'] = message
            save_msg['msg_type'] = 1 # 文本消息
            save_msg['msg_type_name'] = WX_MSG_TYPES.get(save_msg['msg_type'], f"未知类型({save_msg['msg_type']})")
            save_msg['is_self'] = True # 是否自己发送的消息
            save_msg['is_group'] = False # 是否群消息
            save_msg['msg_timestamp'] = datetime.now().timestamp() # 没有相关数据 直接使用当前时间
            save_msg['msg_datetime'] = datetime.fromtimestamp(save_msg['msg_timestamp']).strftime('%Y-%m-%d %H:%M')
            save_msg['wx_user_name'] = wx_config['wx_name']
            save_msg['wx_user_id'] = wx_config['wx_user_id']
            save_msg['room_id'] = contact_name # 暂时用会话名称代替房间ID
            save_msg['room_name'] = contact_name
            save_msg['sender_id'] =wx_config['wx_user_id'] # 自己发送的消息，发送者ID为自己的ID
            save_msg['sender_name'] = wx_config['wx_name']
            save_msg['source_ip'] = ''

            print(f"[SAVE] 发送者: {save_msg['sender_name']}, 消息内容: {save_msg['content']},")
            save_data_to_db(save_msg)
