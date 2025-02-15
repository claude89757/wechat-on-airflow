from datetime import datetime, timedelta
import requests
import json
from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
}

def check_venue_availability():
    url = "https://program.springcocoon.com/szbay/api/services/app/VenueBill/GetVenueBillDataAsync"
    
    headers = {
        "Host": "program.springcocoon.com",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-XSRF-TOKEN": "ntutMqRb0WugZfy7xPzohrV_9ye2tSviscG8iXdqwJ8Wv63Fic7N3NZNHw9gSKOd8g5wfvq3uS2xdUGlMGqit0-RqZWn1Yb2z4eBrLXUbGMlYXxaBL-Bt8rwbMH7D0jdzVYdeQ2",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36 MicroMessenger/6.8.0(0x16080000) NetType/WIFI MiniProgramEnv/Mac MacWechat/WMPF MacWechat/3.8.10(0x13080a11) XWEB/1227",
        "Origin": "https://program.springcocoon.com",
        "Referer": "https://program.springcocoon.com/szbay/AppVenue/VenueBill/VenueBill?VenueTypeID=d3bc78ba-0d9c-4996-9ac5-5a792324decb",
        "Cookie": "HT.LoginType.1=20; HT.App.Type.1=10; HT.Weixin.ServiceType.1=30; HT.Weixin.AppID.1=wx6b10d95e92283e1c; HT.Weixin.OpenID.1=oH5RL5EWB5CjAPKVPOOLlfHm1bV8; HT.EmpID.1=4d5adfce-e849-48d5-b7fb-863cdf34bea0; HT.IsTrainer.1=False; HT.PartID.1=b700c053-71f2-47a6-88a1-6cf50b7cf863; HT.PartDisplayName.1=%e6%b7%b1%e5%9c%b3%e6%b9%be%e4%bd%93%e8%82%b2%e4%b8%ad%e5%bf%83; HT.ShopID.1=4f195d33-de51-495e-a345-09b23f98ce95; HT.ShopDisplayName.1=%e6%b7%b1%e5%9c%b3%e6%b9%be%e5%b0%8f%e7%a8%8b%e5%ba%8f; ASP.NET_SessionId=kzkp4in0ixh5b2ja15ntd5lt; .AspNet.ApplicationCookie=-M7ZlgO39kFB3HKUrbDJ2Xr5BLfSWTo_Ro2VRQf_Pv_g1X50ZymQcwKI4CmPMFDgTdi5e-N0IaORjtRSLVQ1uVoQ9DETv4uMYybiB18vLSEVZ4hlMd8gxdIjjGeupP3HuGFF0dOTvj2zFS1b0dm6EcKMEoQZv7t3dDJ5jsGn71WSI4lB2uGP8tqwwcLVlaAnKvAGf73dCd1uRaUvBawCpy7FcSZyPR4b_UlKGe5UxJgWuaQLseMyxpKriwalXFe4T3ZUcNwOS6bRB0mqSbKWPrgOFiIq0_WRdMAhqSNqg-cvYE7hSI4gFTRCtn_3v6em9kp4RNQqOdz-c50pk1d589Vb7ftvH0tPry8-rLM9yf0p24fR0DL8MKyi-rXTiQ8HTPTdcWrWdL30DtBRNQ4Zye8DA68RA5bV5Y61yWAf51S3s1GvVUsJ1MkBk6dPtsfkWmhG4C7Mx6-MRrMXAzrZZXrE1jB1a7wJIdSziREVZxiaQPcNcYQ5ZvFWnmtAcO_4h50NC714pIFiBdqWJbburJPof87xF6UVyZQcE3t9jqcFFUEBBZpQTiq0wi4Ejmh6CFcE9RqhaG1AUr5U6BV4Q7h3NEE3AjOtHcCx6lz-nlv0wIxs"
    }
    
    data = {
        "VenueTypeID": "d3bc78ba-0d9c-4996-9ac5-5a792324decb",
        "VenueTypeDisplayName": "",
        "IsGetPrice": "true",
        "isApp": "true",
        "billDay": "2025-02-15",
        "webApiUniqueID": "2459c619-967d-2294-0701-17e57c740489"
    }

    try:
        response = requests.post(url, headers=headers, data=data, verify=False, timeout=10)
        response.raise_for_status()  # 检查请求是否成功
        result = response.json()
        print(f"查询时间: {datetime.now()}")
        print(f"API返回结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求失败: {str(e)}")

# 创建DAG
dag = DAG(
    'szw_tennis_court_checker',
    default_args=default_args,
    description='深圳湾网球场地可用性检查',
    schedule_interval='*/5 * * * *',  # 每5分钟执行一次
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['tennis'],
)

# 创建任务
check_task = PythonOperator(
    task_id='check_venue_availability',
    python_callable=check_venue_availability,
    dag=dag,
)
