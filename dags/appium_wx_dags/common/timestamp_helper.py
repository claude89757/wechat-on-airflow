from datetime import datetime

def convert_time_to_timestamp(msg_time: str) -> float:
    """
        将微信消息的时间字符串转换为时间戳
    Args:
        msg_time: 微信消息的时间字符串，如 "14:30" 或者 "下午2:30"

    Returns:
        时间戳，如 1641869800.0
    """

    # 如果是 "14:30" 这种格式，无需预处理
    # 如果是 "下午2:30" 这种格式，需要将其转换为 "14:30" 这种格式
    if '早上' in msg_time:
        msg_time = msg_time.replace('早上', '')

    if '下午' in msg_time or '晚上' in msg_time:
        # 去除中文，增加12小时
        msg_time = msg_time.replace('下午', '').replace('晚上', '')
        hour = int(msg_time.split(':')[0]) + 12
        minute = int(msg_time.split(':')[1])
        msg_time = f'{hour}:{minute}'

    current_date = datetime.now().strftime('%Y-%m-%d')
    timestamp = datetime.strptime(f'{current_date} {msg_time}', '%Y-%m-%d %H:%M').timestamp()

    return timestamp