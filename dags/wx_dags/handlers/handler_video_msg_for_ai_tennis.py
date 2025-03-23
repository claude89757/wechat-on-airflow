
import re

from airflow.api.common.trigger_dag import trigger_dag
from datetime import datetime, timedelta, timezone

def handler_video_msg(**context):
    """
    处理视频消息
    """
    # 视频消息
    message_data = context.get('dag_run').conf
    message_data['id'] = int(message_data['id'])
    room_id = message_data.get('roomid')
    sender = message_data.get('sender')
    msg_id = message_data.get('id')
    msg_type = message_data.get('type')
    content = message_data.get('content', '')
    is_self = message_data.get('is_self', False)  # 是否自己发送的消息
    is_group = message_data.get('is_group', False)  # 是否群聊
    current_msg_timestamp = message_data.get('ts')
    source_ip = message_data.get('source_ip')
    formatted_roomid = re.sub(r'[^a-zA-Z0-9]', '', str(room_id))  # 用于触发DAG的run_id

    now = datetime.now(timezone.utc)
    execution_date = now + timedelta(microseconds=hash(msg_id) % 1000000)  # 添加随机毫秒延迟
    run_id = f'{formatted_roomid}_{sender}_{msg_id}_{now.timestamp()}'
    print(f"[WATCHER] {room_id} 收到视频消息, 触发AI视频处理DAG")
    trigger_dag(
        dag_id='tennis_action_score_v2',
        conf={"current_message": message_data},
        run_id=run_id,
        execution_date=execution_date
    )
