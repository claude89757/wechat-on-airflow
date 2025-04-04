import datetime
import json

def main():
    """
    获取当前时间以及今天、明天、后天、大后天的日期信息
    返回JSON格式的数据
    """
    # 获取当前UTC时间
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    
    # 转换为北京时间 (UTC+8)
    beijing_offset = datetime.timedelta(hours=8)
    now = now_utc.replace(tzinfo=datetime.timezone.utc).astimezone(datetime.timezone(beijing_offset))
    
    # 获取今天、明天、后天、大后天的日期
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    day_after_tomorrow = today + datetime.timedelta(days=2)
    two_days_after_tomorrow = today + datetime.timedelta(days=3)
    
    # 星期几的中文表示
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    
    # 获取各天的星期几
    today_weekday = weekday_names[today.weekday()]
    tomorrow_weekday = weekday_names[tomorrow.weekday()]
    day_after_tomorrow_weekday = weekday_names[day_after_tomorrow.weekday()]
    two_days_after_tomorrow_weekday = weekday_names[two_days_after_tomorrow.weekday()]
    
    # 组织数据
    result = (
        f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')} (北京时间)\n"
        f"今天日期: {today.strftime('%Y-%m-%d')} {today_weekday}\n" 
        f"明天日期: {tomorrow.strftime('%Y-%m-%d')} {tomorrow_weekday}\n"
        f"后天日期: {day_after_tomorrow.strftime('%Y-%m-%d')} {day_after_tomorrow_weekday}\n"
        f"大后天日期: {two_days_after_tomorrow.strftime('%Y-%m-%d')} {two_days_after_tomorrow_weekday}"
    )
    
    return {
        "date_info": result
    }