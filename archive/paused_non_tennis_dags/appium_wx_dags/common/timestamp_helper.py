from datetime import datetime
import re

def convert_time_to_timestamp(msg_time: str) -> float:
    """
        将微信消息的时间字符串转换为时间戳
    Args:
        msg_time: 微信消息的时间字符串，如 "14:30"、"下午2:30"、"2025-07-04 中午12:37"

    Returns:
        时间戳，如 1641869800.0
    """
    
    # 检查是否包含日期
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', msg_time)
    if date_match:
        date_str = date_match.group(1)
        # 从原始字符串中移除日期部分，只保留时间部分
        msg_time = msg_time.replace(date_str, '').strip()
    else:
        # 如果没有日期，使用当前日期
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    # 处理各种时间格式
    if '早上' in msg_time:
        msg_time = msg_time.replace('早上', '')
    
    elif '中午' in msg_time:
        msg_time = msg_time.replace('中午', '')
        # 如果是12点，不需要调整，其他时间可能需要根据实际情况调整
    
    elif '下午' in msg_time or '晚上' in msg_time:
        # 去除中文，增加12小时
        msg_time = msg_time.replace('下午', '').replace('晚上', '')
        hour = int(msg_time.split(':')[0])
        # 避免将下午12点转换为24点
        if hour != 12:
            hour += 12
        minute = int(msg_time.split(':')[1])
        msg_time = f'{hour}:{minute}'
    
    # 组合日期和时间，并转换为时间戳
    try:
        timestamp = datetime.strptime(f'{date_str} {msg_time}', '%Y-%m-%d %H:%M').timestamp()
        return timestamp
    except ValueError:
        # 如果格式不匹配，尝试其他可能的格式
        try:
            # 尝试处理可能的单位数小时格式，如 "中午1:30"
            hour, minute = map(int, msg_time.split(':'))
            formatted_time = f'{hour:02d}:{minute:02d}'
            timestamp = datetime.strptime(f'{date_str} {formatted_time}', '%Y-%m-%d %H:%M').timestamp()
            return timestamp
        except ValueError as e:
            raise ValueError(f"无法解析时间格式: {msg_time}, 错误: {str(e)}")