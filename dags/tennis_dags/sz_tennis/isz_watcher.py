#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/05/30
@Author  : claude89757
@File    : isz_watcher.py
@Software: PyCharm
动态创建多个爱深圳场地的监控DAG
"""
import time
import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from datetime import timedelta
import random
import requests

# 修复导入路径 - 使用绝对导入
from .isz_tools.get_isz_data import get_free_venue_list
from .isz_tools.config import CD_TIME_RANGE_INFOS, CD_ACTIVE_DAY_INFOS, COURT_NAME_INFOS

# 场地配置信息 - 参考config.py中的静态配置
VENUE_CONFIGS = {
    "香蜜体育": {
        "sales_item_id": "100341",
        "venue_name": "香蜜体育",
        "dag_id": "isz_xiangmi_tennis_watcher",
        "description": "爱深圳香蜜体育网球场巡检",
        "schedule_interval": "*/3 * * * *",  # 每3分钟执行一次
        "time_range": CD_TIME_RANGE_INFOS.get("香蜜体育", {"start_time": "07:00", "end_time": "22:30"}),
        "active_days": CD_ACTIVE_DAY_INFOS.get("香蜜体育", 2)
    },
    "黄木岗": {
        "sales_item_id": "100344", 
        "venue_name": "黄木岗",
        "dag_id": "isz_huangmugang_tennis_watcher",
        "description": "爱深圳黄木岗网球场巡检",
        "schedule_interval": "1-59/3 * * * *",  # 每3分钟执行一次，从第1分钟开始
        "time_range": CD_TIME_RANGE_INFOS.get("黄木岗", {"start_time": "07:00", "end_time": "22:30"}),
        "active_days": CD_ACTIVE_DAY_INFOS.get("黄木岗", 2)
    },
    "网羽中心": {
        "sales_item_id": "100704",
        "venue_name": "网羽中心", 
        "dag_id": "isz_wangyu_tennis_watcher",
        "description": "爱深圳网羽中心网球场巡检",
        "schedule_interval": "2-59/3 * * * *",  # 每3分钟执行一次，从第2分钟开始
        "time_range": CD_TIME_RANGE_INFOS.get("网羽中心", {"start_time": "07:00", "end_time": "23:00"}),
        "active_days": CD_ACTIVE_DAY_INFOS.get("网羽中心", 2)
    },
    "华侨城": {
        "sales_item_id": "105143",
        "venue_name": "华侨城",
        "dag_id": "isz_huaqiaocheng_tennis_watcher", 
        "description": "爱深圳华侨城体育中心网球场巡检",
        "schedule_interval": "0-59/3 * * * *",  # 每3分钟执行一次，从第0分钟开始
        "time_range": CD_TIME_RANGE_INFOS.get("华侨城", {"start_time": "07:00", "end_time": "22:00"}),
        "active_days": CD_ACTIVE_DAY_INFOS.get("华侨城", 3)
    }
}

# DAG的默认参数
default_args = {
    'owner': 'claude89757',
    'depends_on_past': False,
    'start_date': datetime.datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def print_with_timestamp(*args, **kwargs):
    """打印函数带上当前时间戳"""
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]", time.localtime())
    print(timestamp, *args, **kwargs)

def get_proxy_list():
    """获取代理列表"""
    try:
        # 获取系统代理
        system_proxy = Variable.get("PROXY_URL", default_var="")
        if system_proxy:
            proxies = {"https": system_proxy}
            print_with_timestamp(f"使用系统代理: {system_proxy}")
        else:
            proxies = None
            print_with_timestamp("未配置系统代理，直接访问")

        # 获取代理列表
        url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/isz_https_proxies.txt"
        print_with_timestamp(f"正在获取代理列表: {url}")
        
        response = requests.get(url, proxies=proxies, timeout=30)
        if response.status_code != 200:
            print_with_timestamp(f"获取代理列表失败，状态码: {response.status_code}")
            return []
            
        text = response.text.strip()
        if not text:
            print_with_timestamp("代理列表为空")
            return []
            
        # 处理代理格式，确保格式正确
        proxy_lines = [line.strip() for line in text.split("\n") if line.strip() and ":" in line.strip()]
        proxy_list = []
        
        for line in proxy_lines:
            try:
                # 验证代理格式 ip:port
                parts = line.split(":")
                if len(parts) == 2 and parts[0] and parts[1].isdigit():
                    proxy_dict = {"https": f"http://{line}"}
                    proxy_list.append(proxy_dict)
            except Exception as e:
                print_with_timestamp(f"跳过无效代理格式: {line}, 错误: {e}")
                continue
        
        random.shuffle(proxy_list)
        print_with_timestamp(f"成功加载 {len(proxy_list)} 个有效代理")
        
        # 如果没有可用代理，返回空列表
        if not proxy_list:
            print_with_timestamp("❌ 错误: 没有可用代理，无法进行请求")
            return []
            
        print_with_timestamp(f"代理列表准备完成，总计 {len(proxy_list)} 个代理")
        return proxy_list
        
    except Exception as e:
        print_with_timestamp(f"获取代理列表失败: {e}")
        print_with_timestamp("❌ 错误: 无法获取代理，无法进行请求")
        return []

def create_venue_check_function(venue_key, venue_config):
    """为每个场地创建专门的检查函数"""
    def check_venue_courts():
        """检查指定场地的网球场"""
        if datetime.time(0, 0) <= datetime.datetime.now().time() < datetime.time(7, 0):
            print_with_timestamp("每天0点-7点不巡检")
            return
        
        run_start_time = time.time()
        print_with_timestamp(f"开始检查{venue_config['venue_name']}...")

        # 获取代理列表
        proxy_list = get_proxy_list()
        
        # 要发送的通知列表
        up_for_send_data_list = []
        
        # 检查未来N天的场地（根据场地活跃天数配置）
        check_days = venue_config['active_days']
        for index in range(0, check_days):
            input_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%Y-%m-%d')
            inform_date = (datetime.datetime.now() + datetime.timedelta(days=index)).strftime('%m-%d')
            
            try:
                print_with_timestamp(f"正在查询{venue_config['venue_name']} {input_date}的场地信息...")
                court_data = get_free_venue_list(
                    salesItemId=venue_config['sales_item_id'],
                    check_date=input_date,
                    proxy_list=proxy_list
                )
                print_with_timestamp(f"{venue_config['venue_name']} {input_date} 场地数据: {court_data}")
                time.sleep(2)  # 避免请求过于频繁
                
                for venue_id, free_slots in court_data.items():
                    if free_slots:
                        filtered_slots = []
                        check_date = datetime.datetime.strptime(input_date, '%Y-%m-%d')
                        is_weekend = check_date.weekday() >= 5
                        
                        # 获取场地的时间范围
                        time_range = venue_config['time_range']
                        venue_start_hour = int(time_range['start_time'].split(':')[0])
                        venue_end_hour = int(time_range['end_time'].split(':')[0])
                        
                        for slot in free_slots:
                            start_hour = int(slot[0].split(':')[0])
                            end_hour = int(slot[1].split(':')[0])
                            
                            # 确保时间段在场地营业时间内
                            if start_hour < venue_start_hour or end_hour > venue_end_hour:
                                continue
                                
                            if is_weekend:
                                # 周末关注下午和晚上的场地（15-21点）
                                if 15 <= start_hour < 21:
                                    filtered_slots.append(slot)
                            else:
                                # 工作日关注晚上的场地（18-21点）
                                if 18 <= start_hour < 21:
                                    filtered_slots.append(slot)
                        
                        if filtered_slots:
                            up_for_send_data_list.append({
                                "date": inform_date,
                                "venue_id": venue_id,
                                "venue_name": venue_config['venue_name'],
                                "free_slot_list": filtered_slots
                            })
                            
            except Exception as e:
                print_with_timestamp(f"查询{venue_config['venue_name']} {input_date}场地信息出错: {str(e)}")
                continue

        # 处理通知逻辑
        if up_for_send_data_list:
            cache_key = f"ISZ_{venue_key}_网球场"
            sended_msg_list = Variable.get(cache_key, deserialize_json=True, default_var=[])
            up_for_send_msg_list = []
            
            for data in up_for_send_data_list:
                date = data['date']
                venue_id = data['venue_id']
                venue_name = data['venue_name']
                free_slot_list = data['free_slot_list']
                
                date_obj = datetime.datetime.strptime(f"{datetime.datetime.now().year}-{date}", "%Y-%m-%d")
                weekday = date_obj.weekday()
                weekday_str = ["一", "二", "三", "四", "五", "六", "日"][weekday]
                
                for free_slot in free_slot_list:
                    court_name = COURT_NAME_INFOS.get(venue_id, "")
                    notification = f"【{venue_name}{court_name}】星期{weekday_str}({date})空场: {free_slot[0]}-{free_slot[1]}"
                    if notification not in sended_msg_list:
                        up_for_send_msg_list.append(notification)

            # 发送微信消息
            if up_for_send_msg_list:
                all_in_one_msg = "\n".join(up_for_send_msg_list)
                
                # 获取微信群配置
                chat_names = Variable.get("SZ_TENNIS_CHATROOMS", default_var="")
                zacks_up_for_send_msg_list = Variable.get("ZACKS_UP_FOR_SEND_MSG_LIST", default_var=[], deserialize_json=True)
                
                for contact_name in str(chat_names).splitlines():
                    if contact_name.strip():
                        zacks_up_for_send_msg_list.append({
                            "room_name": contact_name.strip(),
                            "msg": all_in_one_msg
                        })
                
                Variable.set("ZACKS_UP_FOR_SEND_MSG_LIST", zacks_up_for_send_msg_list, serialize_json=True)
                sended_msg_list.extend(up_for_send_msg_list)

            # 更新已发送消息的缓存
            description = f"{venue_config['venue_name']}网球场场地通知 - 最后更新: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            Variable.set(
                key=cache_key,
                value=sended_msg_list[-100:],  # 只保留最近100条
                description=description,
                serialize_json=True
            )
            print_with_timestamp(f"更新{cache_key}缓存，共{len(sended_msg_list)}条消息")
        else:
            print_with_timestamp(f"{venue_config['venue_name']}没有空场")

        run_end_time = time.time()
        execution_time = run_end_time - run_start_time
        print_with_timestamp(f"{venue_config['venue_name']}检查完成，耗时：{execution_time:.2f}秒")

    return check_venue_courts

# 动态创建DAG
def create_venue_dag(venue_key, venue_config):
    """为每个场地创建独立的DAG"""
    dag = DAG(
        venue_config['dag_id'],
        default_args=default_args,
        description=venue_config['description'],
        schedule_interval=venue_config['schedule_interval'],
        max_active_runs=1,
        dagrun_timeout=timedelta(minutes=15),
        catchup=False,
        tags=['深圳', '爱深圳', '网球场', venue_key]
    )

    # 创建检查任务
    check_task = PythonOperator(
        task_id=f'check_{venue_key}_tennis_courts',
        python_callable=create_venue_check_function(venue_key, venue_config),
        dag=dag,
    )

    return dag

# 为每个场地创建DAG
for venue_key, venue_config in VENUE_CONFIGS.items():
    dag_id = venue_config['dag_id']
    # 将DAG注册到全局命名空间，这样Airflow才能发现它们
    globals()[dag_id] = create_venue_dag(venue_key, venue_config)

# 如果需要测试单个场地
if __name__ == "__main__":
    # 测试香蜜体育场地查询
    test_venue = VENUE_CONFIGS["香蜜体育"]
    test_function = create_venue_check_function("香蜜体育", test_venue)
    test_function() 
