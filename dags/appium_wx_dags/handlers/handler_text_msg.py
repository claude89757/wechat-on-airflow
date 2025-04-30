# 标准库
import re

# airflow库
from airflow.models import Variable
# 第三方库
from utils.dify_sdk import DifyAgent
# 自定义库
from utils.appium.wx_appium import send_wx_msg_by_appium


def handle_text_messages(**context):
    """处理文本消息"""
    print(f"[HANDLE] 处理文本消息")
    task_index = int(context['task_instance'].task_id.split('_')[-1])
    appium_server_info = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)[task_index]
    print(f"[HANDLE] 获取Appium服务器信息: {appium_server_info}")

    wx_name = appium_server_info['wx_name']
    device_name = appium_server_info['device_name']
    appium_url = appium_server_info['appium_url']
    dify_api_url = appium_server_info['dify_api_url']
    dify_api_key = appium_server_info['dify_api_key']

    # 获取XCOM
    recent_new_msg = context['ti'].xcom_pull(key=f'text_msg_{task_index}', task_ids=f'wx_watcher_{task_index}')

    print(f"[HANDLE] 获取XCOM: {recent_new_msg}")

    # 检查是否有消息任务，有则处理
    if recent_new_msg:
        # 发送消息
        for contact_name, messages in recent_new_msg.items():
            msg_list = []
            for message in messages:
                msg_list.append(message['msg'])
            msg = "\n".join(msg_list)

            # AI 回复
            response_msg_list = handle_msg_by_ai(dify_api_url, dify_api_key, wx_name, contact_name, msg)

            if response_msg_list:
                send_wx_msg_by_appium(appium_url, device_name, contact_name, response_msg_list)
            else:
                print(f"[HANDLE] 没有AI回复")
    else:
        print(f"[HANDLE] 没有文本消息处理任务")

    return recent_new_msg


def handle_msg_by_ai(dify_api_url, dify_api_key, wx_user_name, room_id, msg) -> list:
    """
    使用AI回复消息
    Args:
        wx_user_name (str): 微信用户名
        room_id (str): 房间ID(这里指会话的名称)
        msg (str): 消息内容
    Returns:
        list: AI回复内容列表
    """
    
    # 初始化DifyAgent
    dify_agent = DifyAgent(api_key=dify_api_key, base_url=dify_api_url)

    # 获取会话ID
    dify_user_id = f"{wx_user_name}_{room_id}"
    conversation_id = dify_agent.get_conversation_id_for_room(dify_user_id, room_id)

    # 获取在线图片信息
    dify_files = []
    online_img_info = Variable.get(f"{wx_user_name}_{room_id}_online_img_info", default_var={}, deserialize_json=True)
    if online_img_info:
        dify_files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": online_img_info.get("id", "")
        })
    
    # 获取AI回复
    try:
        print(f"[WATCHER] 开始获取AI回复")
        full_answer, metadata = dify_agent.create_chat_message_stream(
            query=msg,
            user_id=dify_user_id,
            conversation_id=conversation_id,
            files=dify_files,
            inputs={}
        )
    except Exception as e:
        if "Variable #conversation.section# not found" in str(e):
            # 清理会话记录
            conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
            if room_id in conversation_infos:
                del conversation_infos[room_id]
                Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
            print(f"已清除用户 {dify_user_id} 在房间 {room_id} 的会话记录")
            
            # 重新请求
            print(f"[WATCHER] 重新请求AI回复")
            full_answer, metadata = dify_agent.create_chat_message_stream(
                query=msg,
                user_id=dify_user_id,
                conversation_id=None,  # 使用新的会话
                files=dify_files,
                inputs={}
            )
        else:
            raise
    print(f"full_answer: {full_answer}")
    print(f"metadata: {metadata}")

    if not conversation_id:
        try:
            # 新会话，重命名会话
            conversation_id = metadata.get("conversation_id")
            dify_agent.rename_conversation(conversation_id, dify_user_id, f"{wx_user_name}_{room_id}")
        except Exception as e:
            print(f"[WATCHER] 重命名会话失败: {e}")

        # 保存会话ID
        conversation_infos = Variable.get(f"{dify_user_id}_conversation_infos", default_var={}, deserialize_json=True)
        conversation_infos[room_id] = conversation_id
        Variable.set(f"{dify_user_id}_conversation_infos", conversation_infos, serialize_json=True)
    else:
        # 旧会话，不重命名
        pass
    
    response_msg_list = []
    for response_part in re.split(r'\\n\\n|\n\n', full_answer):
        response_part = response_part.replace('\\n', '\n')
        if response_part and response_part != "#沉默#":  # 忽略沉默
            response_msg_list.append(response_part)

    return response_msg_list
