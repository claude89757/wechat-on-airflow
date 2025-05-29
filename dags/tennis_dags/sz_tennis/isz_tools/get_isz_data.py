import requests
import os
import json
import time
import datetime
from .sign_url_utls import ydmap_sign_url
from .config import CD_TIME_RANGE_INFOS

from airflow.models.variable import Variable

try:
    jsrpc_url = Variable.get("JSRPC_URL")
except Exception as e:
    jsrpc_url = os.getenv("JSRPC_URL")


def timestamp_to_clock(timestamp: int) -> str:
    """
    timestamp 为 Unix 时间戳（毫秒）
    返回值为时钟格式（小时:分钟）
    """
    date = datetime.datetime.fromtimestamp(timestamp / 1000)  # 将毫秒转换为秒
    return date.strftime('%H:%M')


def str_to_timestamp(date_str: str):
    """将字符串日期转换为时间戳, 比如2025-05-30 转换为 1717008000000"""
    return int(datetime.datetime.strptime(date_str, '%Y-%m-%d').timestamp() * 1000)


def get_isz_venue_order_list(salesItemId: str, curDate: str, proxy_list: list = None):
    """
    获取isz的场地订单列表
    :param salesItemId: 场地ID
    :param curDate: 日期（时间戳）
    :return: 场地订单列表(表示已经被预订的场地), 格式如下
    {
    "code": 0,
    "data": [
        {
            "createTime": 1748510527000,
            "dataId": 46041770,
            "dealPlatformId": null,
            "dealPlatformType": 3,
            "dealServiceUserList": [],
            "dealState": null,
            "endTime": 1357005600000,
            "fightDeclaration": null,
            "fightMobile": null,
            "isFightDeal": null,
            "lockId": 46041770,
            "orderId": null,
            "orderId2": null,
            "platformSubIds": "",
            "relType": 222,
            "sellerMessage": "",
            "sportTeamColorRgb": null,
            "sportTeamColorValue": null,
            "sportTeamName": null,
            "startTime": 1357002000000,
            "venueId": 120018
        },
        {
            "createTime": 1748442693000,
            "dataId": 46021372,
            "dealPlatformId": null,
            "dealPlatformType": 3,
            "dealServiceUserList": [],
            "dealState": null,
            "endTime": 1357002000000,
            "fightDeclaration": null,
            "fightMobile": null,
            "isFightDeal": null,
            "lockId": 46021372,
            "orderId": null,
            "orderId2": null,
            "platformSubIds": "",
            "relType": 222,
            "sellerMessage": "",
            "sportTeamColorRgb": null,
            "sportTeamColorValue": null,
            "sportTeamName": null,
            "startTime": 1356994800000,
            "venueId": 120018
        },
        {
            "createTime": 1716895159000,
            "dataId": 235867,
            "dealPlatformId": null,
            "dealPlatformType": 3,
            "dealServiceUserList": [],
            "dealState": null,
            "endTime": 1357048800000,
            "fightDeclaration": null,
            "fightMobile": null,
            "isFightDeal": null,
            "lockId": 32157488,
            "orderId": null,
            "orderId2": null,
            "platformSubIds": "",
            "relType": 43,
            "sellerMessage": "",
            "sportTeamColorRgb": null,
            "sportTeamColorValue": null,
            "sportTeamName": null,
            "startTime": 1357030800000,
            "venueId": 120018
        }
    ],
    "msg": "操作成功",
    "requestId": "1928156774436954112",
    "timestamp": 1748543373225
    }   
    """
    
    # 使用实时时间戳
    current_time = int(time.time() * 1000)
    
    # 构造基础URL（不包含type__1295参数）
    base_url = f"https://isz.ydmap.cn/srv100352/api/pub/sport/venue/getVenueOrderList?" \
               f"salesItemId={salesItemId}&curDate={curDate}&venueGroupId=&t={current_time}"
    
    print(f"步骤1: 生成基础URL（使用实时时间戳）...")
    print(f"基础URL: {base_url}")
    
    # 构造aq函数的输入数据（使用基础URL）
    test_data = {
        "aU": {
            "url": base_url,
            "duration": -166,
            "hackSceneSalesItemId": None,
            "method": "GET"
        },
        "aV": "get",
        "aW": None,
        "aX": {},
        "aY": None
    }
    
    # 调用aq接口获取签名信息
    aq_data = {
        "group": "sign",
        "action": "aq", 
        "param": json.dumps(test_data)
    }
    print(f"\n步骤2: 通过jsrpc服务调用aq函数生成header签名信息...")
    try:
        aq_response = requests.post(jsrpc_url, data=aq_data, timeout=30)
        print(f"aq响应状态码: {aq_response.status_code}")
        
        if aq_response.status_code != 200:
            print(f"aq调用失败: {aq_response.text}")
            return False
            
        aq_result = aq_response.json()
        print(f"aq响应结果: {aq_result}")
        
        if aq_result.get('status') != 200:
            print("aq函数返回错误状态")
            return False
            
        # 解析签名数据
        sign_data = json.loads(aq_result['data'])
        nonce = sign_data['nonce']
        timestamp = sign_data['timestamp']
        signature = sign_data['signature']
        
        print(f"生成的header签名信息:")
        print(f"  nonce: {nonce}")
        print(f"  timestamp: {timestamp}")
        print(f"  signature: {signature}")
        
    except Exception as e:
        print(f"调用aq函数出错: {e}")
        return False
    
    # 使用ydmap_sign_url函数生成包含type__1295的完整URL
    print(f"\n步骤3: 使用ydmap_sign_url函数生成md5__1182参数...")
    try:
        # 注意：ydmap_sign_url函数会打印调试信息并返回完整URL
        full_url_with_timestamp = ydmap_sign_url(base_url, current_time, "md5__1182")
        print(f"生成的完整URL: {full_url_with_timestamp}")
        
    except Exception as e:
        print(f"生成md5__1182参数出错: {e}")
        return False
    
    # 使用生成的签名信息发送请求
    print(f"\n步骤4: 使用生成的签名发送完整请求...")
    headers = {
        'Host': 'isz.ydmap.cn',
        # 'Cookie': '',
        'nonce': nonce,
        # 'openid-token': '',
        # 'server-reflexive-ip': '',
        'entry-tag': '',
        'access-token': '',
        'visitor-id': nonce,  # 随便赋值
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/6.8.0(0x16080000) MacWechat/3.8.10(0x13080a10) XWEB/1227 Flue',
        'accept': 'application/json, text/plain, */*',
        'timestamp': timestamp,
        'signature': signature,
        'tab-id': 'ydmap_7158e4920308caceb125209cb5ca945d',
        'x-requested-with': 'XMLHttpRequest',
        'cross-token': '',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        # 'referer': '',
        'accept-language': 'zh-CN,zh;q=0.9'
    }

    try:
        response = None
        success = False
        
        if proxy_list and len(proxy_list) > 0:
            print(f"======尝试使用代理列表，共 {len(proxy_list)} 个选项（包含直连）")
            
            for i, proxy_config in enumerate(proxy_list):
                try:
                    if proxy_config is None:
                        print(f"[{i+1}/{len(proxy_list)}] 尝试直连（无代理）")
                        response = requests.get(full_url_with_timestamp, headers=headers, timeout=15)
                    else:
                        proxy_str = proxy_config.get('https', 'Unknown')
                        print(f"[{i+1}/{len(proxy_list)}] 尝试使用代理: {proxy_str}")
                        response = requests.get(full_url_with_timestamp, headers=headers, timeout=15, proxies=proxy_config)
                    
                    # 检查响应
                    if response.status_code == 200:
                        try:
                            response_json = response.json()
                            if isinstance(response_json, dict):
                                print(f"✅ 请求成功！使用{'直连' if proxy_config is None else proxy_config.get('https')}")
                                success = True
                                break
                            else:
                                print(f"❌ 响应格式不正确: {type(response_json)}")
                        except json.JSONDecodeError:
                            print(f"❌ 响应不是有效JSON: {response.text[:200]}")
                    else:
                        print(f"❌ HTTP状态码错误: {response.status_code}")
                        
                except requests.exceptions.Timeout:
                    print(f"❌ 请求超时")
                except requests.exceptions.ConnectionError:
                    print(f"❌ 连接错误")
                except Exception as e:
                    print(f"❌ 请求异常: {e}")
                    
                # 如果不是最后一个代理，稍等一下再试下一个
                if i < len(proxy_list) - 1:
                    time.sleep(1)
        else:
            print(f"代理列表为空，使用直连模式")
            try:
                response = requests.get(full_url_with_timestamp, headers=headers, timeout=15)
                if response.status_code == 200:
                    success = True
                    print(f"✅ 直连请求成功")
            except Exception as e:
                print(f"❌ 直连请求失败: {e}")
        
        if not success or response is None:
            print(f"❌ 所有代理和直连都失败")
            return {}
            
        print(f"目标API响应状态码: {response.status_code}")
        print(f"目标API响应内容前500字符: {response.text[:500]}")
        
        # 检查是否还有签名错误
        if response.status_code == 200:
            try:
                result = response.json()
                print(result)
                if result.get('code') == -1 and '签名错误' in result.get('msg', ''):
                    print("❌ 签名验证失败，仍然提示签名错误")
                    return {}
                else:
                    print("✅ 联合签名验证成功！API返回正常JSON响应")
                    return result
            except json.JSONDecodeError:
                print(response.text)
                # 如果不是JSON响应，可能是HTML页面
                if '<html>' in response.text:
                    print("❌ 返回HTML页面，可能被WAF拦截")
                    return {}
                else:
                    print("✅ 联合签名验证成功！API返回非JSON响应")
                    return {}
        else:
            print(f"❌ 请求失败，状态码: {response.status_code}")
            return {}
            
    except Exception as e:
        print(f"发送目标请求出错: {e}")
        return {}
    

def get_free_venue_list(salesItemId: str, check_date: str, proxy_list: list = None):
    """
    查询空闲场地列表
    :param salesItemId: 销售项目ID
    :param curDate: 日期 格式为 2025-05-30
    :return: 场地列表
    格式如下:
    {
        102930: [['08:00', '22:30']],
        102931: [['08:00', '22:30']],
        102932: [['08:00', '22:30']]
    }
    """
    # 查询已预订的场地列表
    check_date_timestamp = str_to_timestamp(check_date)
    busy_venue_data = get_isz_venue_order_list(salesItemId, check_date_timestamp, proxy_list)

    if not busy_venue_data:
        raise Exception("查询已预订的场地列表失败")

    today_str = datetime.datetime.now().strftime('%Y-%m-%d')
    booked_court_infos = {}
    for data in busy_venue_data['data']:
        start_time = timestamp_to_clock(data['startTime'])
        end_time = timestamp_to_clock(data['endTime'])
        if booked_court_infos.get(data['venueId']):
            booked_court_infos[data['venueId']].append([start_time, end_time])
        else:
            booked_court_infos[data['venueId']] = [[start_time, end_time]]
    available_slots_infos = {}
    for venue_id, booked_slots in booked_court_infos.items():
        if venue_id in [104300, 104301, 104302, 104475]:
            # 黄木岗的训练墙剔除
            continue
        elif venue_id == 117557:
            # 大沙河异常场地数据剔除
            continue
        elif venue_id == 104867 or venue_id == 104861 or venue_id == 104862:
            # 网羽中心异常场地数据剔除
            continue
        elif venue_id == 102930:
            if check_date != today_str:
                # 香蜜6号场，非当日的场地信息过滤
                continue
            else:
                pass
        else:
            pass
        time_range = CD_TIME_RANGE_INFOS.get(venue_id, {"start_time": "08:00", "end_time": "22:00"})
        available_slots = find_available_slots(booked_slots, time_range)
        available_slots_infos[venue_id] = available_slots
    filter_available_slots_infos = {}
    for venue_id, available_slots in available_slots_infos.items():
        if venue_id == 102930 and (available_slots == [['08:00', '22:30']]
                                    or available_slots == [['09:00', '22:30']]
                                    or available_slots == [['10:00', '22:30']]):
            pass
        else:
            filter_available_slots_infos[venue_id] = available_slots
    return filter_available_slots_infos
    

def find_available_slots(booked_slots, time_range):
    """
    根据已预定的时间段，查询可预定的时间段
    """
    print(f"input: {booked_slots}")
    print(f"time_range: {time_range}")
    for slot in booked_slots:
        for index in range(len(slot)):
            if slot[index] == '00:00':
                slot[index] = "23:59"
            else:
                pass
    booked_slots = sorted(booked_slots, key=lambda x: x[0])  # 按开始时间排序
    available_slots = []

    current_time = datetime.datetime.strptime(time_range['start_time'], "%H:%M")
    end_time = datetime.datetime.strptime(time_range['end_time'], "%H:%M")

    for slot in booked_slots:
        slot_start = datetime.datetime.strptime(slot[0], "%H:%M")
        slot_end = datetime.datetime.strptime(slot[1], "%H:%M")

        if current_time < slot_start:
            available_slots.append([current_time.strftime("%H:%M"), slot_start.strftime("%H:%M")])

        # 如果当前时间小于已预定时间段的结束时间，更新当前时间为已预定时间段的结束时间
        if current_time < slot_end:
            current_time = slot_end

    if current_time < end_time:
        available_slots.append([current_time.strftime("%H:%M"), end_time.strftime("%H:%M")])
    print(f"output: {available_slots}")
    return available_slots


if __name__ == "__main__":
    print("开始测试aq函数联合ydmap_sign_url的完整签名功能...")
    # 今天
    # import datetime
    # today = datetime.datetime.now().strftime("%Y-%m-%d")
    # format_today = str_to_timestamp(today)
    # print(format_today)
    # result = get_isz_venue_order_list(salesItemId="100341", curDate=format_today)
    # print(result)

    free_venue_list = get_free_venue_list(salesItemId="100341", check_date="2025-05-30")
    print(f"free_venue_list:============")
    print(free_venue_list)
