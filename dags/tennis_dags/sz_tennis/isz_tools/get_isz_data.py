import requests
import os
import json
import uuid
import time
import datetime
import hashlib
import random
from tennis_dags.sz_tennis.isz_tools.sign_url_utls import ydmap_sign_url
from tennis_dags.sz_tennis.isz_tools.config import CD_TIME_RANGE_INFOS
from tennis_dags.sz_tennis.isz_tools.proxy_manager import update_successful_proxies, remove_failed_proxy

from airflow.models.variable import Variable

try:
    jsrpc_url = Variable.get("JSRPC_URL")
except Exception as e:
    jsrpc_url = os.getenv("JSRPC_URL")


def generate_visitor_id() -> str:
    """
    生成类似于 fdcf82874330f089fca31ca93040472f 格式的visitor_id
    使用随机数据生成32位十六进制字符串
    
    Returns:
        str: 32位十六进制字符串
    """
    # 方法1: 使用uuid4去掉连字符
    # visitor_id = str(uuid.uuid4()).replace('-', '')
    
    # 方法2: 使用MD5哈希随机数据（更接近原格式）
    random_data = f"{time.time()}_{random.randint(100000, 999999)}_{os.urandom(8).hex()}"
    visitor_id = hashlib.md5(random_data.encode()).hexdigest()
    
    # 方法3: 直接生成32位随机十六进制字符串
    # visitor_id = ''.join(random.choices('0123456789abcdef', k=32))
    
    print(f"生成的visitor_id: {visitor_id}")
    return visitor_id


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


def generate_signature_and_url(salesItemId: str, curDate: str, visitor_id: str):
    """
    生成签名信息和完整URL
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
        "aX": {
            "accept": "application/json, text/plain, */*",
            "x-requested-with": "XMLHttpRequest",
            "access-token": "",
            "openid-token": "",
            "cross-token": "",
            "entry-tag": "",
            "server-reflexive-ip": "",
            "visitor-id": visitor_id,
            "tab-id": "ydmap_ae807e5264e3b0c115684a313fac2c7e"
        },
        "aY": None
    }
    
    # 调用aq接口获取签名信息
    aq_data = {
        "group": "sign",
        "action": "ap", 
        "param": json.dumps(test_data)
    }
    print(f"\n步骤2: 通过jsrpc服务调用aq函数生成header签名信息...")
    try:
        aq_response = requests.post(jsrpc_url, data=aq_data, timeout=30)
        print(f"aq响应状态码: {aq_response.status_code}")
        
        if aq_response.status_code != 200:
            print(f"aq调用失败: {aq_response.text}")
            return None, None, None, None, None
            
        aq_result = aq_response.json()
        print(f"aq响应结果: {aq_result}")
        
        if aq_result.get('status') != 200:
            print("aq函数返回错误状态")
            return None, None, None, None, None
            
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
        return None, None, None, None, None
    
    # 使用ydmap_sign_url函数生成包含type__1295的完整URL
    print(f"\n步骤3: 使用ydmap_sign_url函数生成md5__1182参数...")
    try:
        # 注意：ydmap_sign_url函数会打印调试信息并返回完整URL
        full_url_with_timestamp = ydmap_sign_url(base_url, current_time, "md5__1182")
        print(f"生成的完整URL: {full_url_with_timestamp}")
        
    except Exception as e:
        print(f"生成md5__1182参数出错: {e}")
        return None, None, None, None, None
    
    return nonce, timestamp, signature, full_url_with_timestamp


def get_isz_venue_order_list(salesItemId: str, curDate: str, proxy_list: list = None):
    """
    获取isz的场地订单列表
    :param salesItemId: 场地ID
    :param curDate: 日期（时间戳）
    :param proxy_list: 代理列表（如果为None则自动获取）
    :return: 场地订单列表(表示已经被预订的场地)
    """
    response = None
    successful_proxy = None

    # 使用当日的日期作为visitor_id
    visitor_id = generate_visitor_id()

    if proxy_list:
        # 使用代理进行请求
        print(f"======使用提供的代理列表，共 {len(proxy_list)} 个代理======")
        for i, proxy_config in enumerate(proxy_list):
            try:
                # 每次请求前重新生成签名
                print(f"[{i+1}/{len(proxy_list)}] 重新生成签名并发送请求...")
                nonce, timestamp, signature, full_url_with_timestamp = generate_signature_and_url(salesItemId, curDate, visitor_id)
                
                if not all([nonce, timestamp, signature, full_url_with_timestamp]):
                    print(f"❌ 签名生成失败，跳过此次请求")
                    continue
                
                # 构建请求头
                headers = {
                    'Host': 'isz.ydmap.cn',
                    # 'Cookie': '',
                    'referer': 'https://isz.ydmap.cn/booking/schedule/101332?salesItemId=100341',
                    'x-requested-with': 'XMLHttpRequest',
                    'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148/openweb=paschybrid/SZSMT_IOS,VERSION:4.9.9',
                    'openid-token': '',
                    'entry-tag': '',
                    'visitor-id': visitor_id,
                    'signature': signature,
                    'sec-fetch-dest': 'empty',
                    'cross-token': '',
                    'sec-fetch-site': 'same-origin',
                    'nonce': nonce,
                    'tab-id': 'ydmap_ae807e5264e3b0c115684a313fac2c7e',
                    'timestamp': timestamp,
                    'accept-language': 'zh-CN,zh-Hans;q=0.9',
                    # 'access-token': '',
                    'accept': 'application/json, text/plain, */*',
                    'server-reflexive-ip': '',
                    'sec-fetch-mode': 'cors'
                }
                
                if proxy_config is None:
                    print(f"使用直连模式")
                    response = requests.get(full_url_with_timestamp, headers=headers, timeout=15)
                else:
                    # 使用代理（参考jdwx_watcher.py的做法）
                    print(f"使用代理: {proxy_config}")
                    response = requests.get(full_url_with_timestamp, headers=headers, timeout=15, proxies=proxy_config)
                
                # 检查响应
                print(f"raw response: {str(response.text)[:200]}")
                if response.status_code == 200:
                    try:
                        response_json = response.json()
                        if isinstance(response_json, dict) and response_json.get('code') == 0:
                            print(f"✅ 请求成功！")
                            successful_proxy = proxy_config
                            break
                        else:
                            print(f"❌ 响应格式错误")
                    except json.JSONDecodeError:
                        print(f"❌ 响应不是JSON格式")
                else:
                    print(f"❌ HTTP状态码: {response.status_code}")
                        
            except requests.exceptions.Timeout:
                print(f"❌ 请求超时")
            except requests.exceptions.ConnectionError:
                print(f"❌ 连接错误")
            except Exception as e:
                print(f"❌ 请求异常: {e}")
                
            # 如果使用了代理但请求失败，从缓存中移除
            if proxy_config is not None:
                remove_failed_proxy(proxy_config)
                
            # 如果不是最后一个代理，稍等一下再试下一个
            if i < len(proxy_list) - 1:
                time.sleep(1)
        
        # 如果有成功的代理，添加到缓存
        if successful_proxy is not None:
            update_successful_proxies(successful_proxy)
    else:
        print(f"❌ 没有可用的代理，使用直连模式")
        nonce, timestamp, signature, full_url_with_timestamp = generate_signature_and_url(salesItemId, curDate, visitor_id)
        # 构建请求头
        headers = {
            'Host': 'isz.ydmap.cn',
            'Cookie': 'ssxmod_itna=eqjOAKDK7IxmgDUxBPBtiOD2DuxYqjIqGdq+Dgn==exiwoDtd55jjXqjTtIfrDlc74DZDGKGFDQeDvI7nF+oI+iGaeT/Wj7b6e/Q1GGNU/zrBpXUi1Qxi8DG+YGyDB9p6TDeeDBnqG6dDD4D5gKDaguz/PYDo=5Dwo+tjBwqgDpF5BuD=l+oj0DaTjGooiTedji4qA+qL0ipff+jLIDD=g08eA+DD===; ssxmod_itna2=eqjOAKDK7IxmgDUxBPBtiOD2DuxYqjIqGdq+Dgn==exiwoDtd55jjXqjTtIDnxnIwHjKDGXxQDjbwxYqtmAq5YTAChr4TL8nWTpjGRbEF5hqXBLqj5KLI=buAwn1hcPWpbvB4gWNTWRkY1W4e1ykIieD60RzYZ4Hr2+qP+W+RoopoUFzWEEHO+va1K3WIYpmdGexrYw+bpBOa2qDwgierl4pyAe4=1kUQ2ACv69xIexpW277r=iUyO4FXC0df8b4ebaxR1WfPD2mQ66Gor0xsmr44D==; tfstk=gq0mXSMqMJYnVEp824aXYxQfM1MDlra_UAQTBPew48ySMZIt_FPieA2TbKGtElDrFrhx6qHuQAkqDVFxBNDu65PVu-rNG0MKTZ3vcPQgkPawppLpJSGb5P8_cLOchzP3gFF47-zbz2inL_LpJjGVyozSwe39NYFLURza0PSza8NG7OkaggRu_5BVbZkwZQVgTS7a3S7zUSNQ7Rka7QczF5zagAzw_p7UHjljzLhsOPc_q_0zio2Eg-5Pa0rFpRc4ENSe6SqcDjyl7Nurj0pRg-9ciJmKOVDmUC7aI0o-T8Dy_Nyi4cuYcPsrygSUJ5Q_aC3lfgE4N72dtbg_Bf6sJGAkZMr707Ny2QAlfGZ4N72pZQjeOoP7a3C..; acw_sc__v3=684c5f1da5b77e3b2321c6056383c6664b1f599b; Hm_lpvt_2e26229fff5c7d4d4029787caaf3d50b=1749835545; Hm_lvt_2e26229fff5c7d4d4029787caaf3d50b=1749695779,1749729683,1749819407,1749828283; acw_tc=ac11000117498355379155547e006ee5e8b3cc87f2de00ce1a0893d916eedc; HMACCOUNT=91FD09D28A72BAB9; _c_WBKFRo=ynF9Q0rYCLh3xnTUC6A2uDKdnCaKTMKV0j4tSn5S; gdxidpyhxdE=eqB%2F4WnId0sHDQ3B19tK3bkmuNXJdrKqbHD5XgQ4Raa3qeVTdpAU6IG5smd7Vk%5Cq7GOanEVufEsdKvvYav2LAU4%2BjQg0CgCW%5CaTfS6nCSAAaZyTbnWlK2nODDeKbWWDzZjgI5j5GjY2pGc9d3QX2nMgc9Txcxt0CL%2FEUyIeKj%2B%2F%5CP%2FzS%3A1749644351976; YdmapKey-100352=A69DF084ACB81EFA75E5C91F13DA147178D5481CA763F22FD73BD2C8697D71DC040E38A265EEB4A2F35FD1136888BE39EB63A8C242512C5D8CCCEF73E22C9F16E6B45F2D09B49EB4408D00CB22173CC3AE7F3C3DEFD40734D0B8F5651B8609BDE6310D2E3F8BAB5327D41B5C93E4F0030B7E2EE3F6F872C789B0854E184025900229C4253D8B933731963FAF638ECC36115F0CE4D1479B86AC8EB8BA30EBA5A9187BEF75C2EA2C14DB7164DDEF9D3EE2430D41697CE63850C114DFE09F4C2B9FC9F1268626ABF98C6C84001A15A7AAEB97FF4DD9E6E5A995C3DDB4ED2F7567E1280701319CF9E8E5EFDD1DEA9238D738DB7F0318E4EF1A133A787DF241CFB2D8F7A3B5ADE58A278A406404983139B7D28F43CBA0296FE8C6A7D8DFC996E823BDFFC363B9587FCCA4315C11C8F06511E57751A90F5F5BD6C43428339C280FD9A989E0D63BDF28C914A3F182D99E2CBB93',
            'referer': 'https://isz.ydmap.cn/booking/schedule/101332?salesItemId=100341',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148/openweb=paschybrid/SZSMT_IOS,VERSION:4.9.9',
            'openid-token': '',
            'entry-tag': '',
            'visitor-id': visitor_id,
            'signature': signature,
            'sec-fetch-dest': 'empty',
            'cross-token': '',
            'sec-fetch-site': 'same-origin',
            'nonce': nonce,
            'tab-id': 'ydmap_ae807e5264e3b0c115684a313fac2c7e',
            'timestamp': timestamp,
            'accept-language': 'zh-CN,zh-Hans;q=0.9',
            # 'access-token': 'eyJhbGciOiJIUzI1NiIsInppcCI6IkRFRiJ9.eJyNj7sKwkAQRf9l6rDsrPtKagWDYAStbMKarBIfG8kmYhT_3bEQLJ1iiplzLtwnNDFCRvvBxvrirqwKkIC_XyFDo4zUhiaBY98QJZ1LuZJ7ox1KUdlUK4mVtdzUKlVGk9nEqd8NB8j27hx9Ap0LdXtZ-JF0JaRGwSVhQ_Tdpj358F_quT00YRZuROfrLR36j5vXP6Elcj5RosQvnlMFQBQsNcwKhhP7_RSfxvlqXixn8HoDZdhGgg.ziVgByeX8pAnHaaDZt8VZ-98dOWLodCus9Xi9DeOTFw',
            'accept': 'application/json, text/plain, */*',
            'server-reflexive-ip': '',
            'sec-fetch-mode': 'cors'
        }
        response = requests.get(full_url_with_timestamp, headers=headers, timeout=15)
        
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
            elif "访问过于频繁" in str(result):
                print("❌ 访问过于频繁，请稍后再试")
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
        print(f"❌ 请求失败，状态码: {response.text}")
        return {}


def get_free_venue_list(salesItemId: str, check_date: str, proxy_list: list = None):
    """
    查询空闲场地列表
    :param salesItemId: 销售项目ID
    :param check_date: 日期 格式为 2025-05-30
    :param proxy_list: 代理列表（如果为None则自动获取）
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
    print("开始测试ISZ数据获取功能...")
    
    # 测试获取场地空闲列表
    import datetime
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    free_venue_list = get_free_venue_list(salesItemId="100341", check_date=today)
    print(f"free_venue_list: {free_venue_list}")
    