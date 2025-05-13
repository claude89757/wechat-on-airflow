import os
import uuid
from datetime import datetime

from airflow.models import Variable

from appium_wx_dags.common.wx_tools import WX_MSG_TYPES
from appium_wx_dags.common.mysql_tools import save_data_to_db
from appium_wx_dags.common.timestamp_helper import convert_time_to_timestamp
from appium_wx_dags.common.wx_tools import upload_image_to_cos


def save_image_to_cos(**context):
    """
    处理图片消息, 上传到COS存储
    """
    task_index = int(context['task_instance'].task_id.split('_')[-1])

    # 获取账号信息
    wx_account_info_list = Variable.get("WX_ACCOUNT_LIST", default_var={}, deserialize_json=True)
    wx_user_name = wx_account_info_list[task_index]['name']
    wx_user_id = wx_account_info_list[task_index]['wxid']

    new_image_msg = context['ti'].xcom_pull(key=f'image_msg_{task_index}')  

    for contact_name, messages in new_image_msg.items():
        for i, message in enumerate(messages):
            image_file_path = str.split(message['msg'], ':')[-1]
            room_id = contact_name # 暂时用会话名称代替房间ID
        try:
            # 上传到COS存储
            cos_path = upload_image_to_cos(image_file_path, wx_user_name, wx_user_id, room_id, context)
            print(f"[UPLOAD] 图片上传到COS成功, COS路径: {cos_path}")

            # 更新图片路径为COS路径
            new_image_msg[contact_name][i]['msg'] = cos_path
            
        except Exception as e:
            print(f"[WATCHER] 保存在线图片信息失败: {e}")

        # TODO:删除本地图
        try:
            os.remove(image_file_path)
        except Exception as e:
            print(f"[WATCHER] 删除本地图片失败: {e}")

    # 将图片消息更新为cos路径
    context['ti'].xcom_push(key=f'image_cos_msg_{task_index}', value=new_image_msg)


def save_image_msg_to_db(**context):
    """保存图片消息到数据库"""
    print(f"[SAVE] 保存图片消息到数据库")

    task_index = int(context['task_instance'].task_id.split('_')[-1])

    # 获取账号信息
    wx_account_info_list = Variable.get("WX_ACCOUNT_LIST", default_var={}, deserialize_json=True)

    # 提交对方发送的图片信息
    recent_new_msg = context['ti'].xcom_pull(key=f'image_cos_msg_{task_index}')
    for contact_name, messages in recent_new_msg.items():
        for message in messages:
            save_msg = {}
            save_msg['msg_id'] = str(uuid.uuid4())
            save_msg['content'] = message['msg'] # 图片COS路径
            save_msg['msg_type'] = 3 # 图片消息
            save_msg['msg_type_name'] = WX_MSG_TYPES.get(save_msg['msg_type'], f"未知类型({save_msg['msg_type']})")
            save_msg['is_self'] = False # 是否自己发送的消息
            save_msg['is_group'] = False # 是否群消息
            save_msg['msg_timestamp'] = convert_time_to_timestamp(message['msg_time'])
            save_msg['msg_datetime'] = datetime.fromtimestamp(save_msg['msg_timestamp']).strftime('%Y-%m-%d %H:%M')
            save_msg['wx_user_name'] = wx_account_info_list[task_index]['name']
            save_msg['wx_user_id'] = wx_account_info_list[task_index]['wxid']
            save_msg['room_id'] = contact_name # 暂时用会话名称代替房间ID
            save_msg['room_name'] = contact_name
            save_msg['sender_id'] = message['sender'] # 发送者ID，暂时用发送者名称代替
            save_msg['sender_name'] = message['sender']
            save_msg['source_ip'] = ''

            print(f"[SAVE] 发送者: {save_msg['sender_name']}, 消息内容: {save_msg['content']},")
            save_data_to_db(save_msg)

