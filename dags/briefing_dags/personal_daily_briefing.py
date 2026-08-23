from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.briefings.daily_briefing import run_daily_briefing

DAG_ID = "personal_daily_briefing"

with DAG(
    dag_id=DAG_ID,
    default_args={
        "owner": "claude89757",
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
    },
    description="每天生成带来源的个人关注话题简报并发送到微信",
    schedule="0 9 * * *",
    start_date=datetime(2026, 8, 24, tzinfo=ZoneInfo("Asia/Shanghai")),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=25),
    catchup=False,
    tags=["个人微信", "每日简报", "AI", "新闻"],
) as dag:
    generate_and_send = PythonOperator(
        task_id="generate_and_send",
        python_callable=run_daily_briefing,
    )
