import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.baoti_ydmap_watcher import run_check_tennis_courts

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "start_date": datetime.datetime(2026, 11, 26, tzinfo=ZoneInfo("Asia/Shanghai")),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "宝安网球中心巡检",
    default_args=DEFAULT_ARGS,
    description="宝安网球中心巡检 - YDMap 树莓派浏览器代理采集（bawtt.ydmap.cn）",
    # Runs every 2 minutes on odd minutes in an isolated browser pool/port; rotates across 3 products (6 min full cycle).
    schedule="1-59/2 * * * *",
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=["深圳"],
)

PythonOperator(
    task_id="check_tennis_courts",
    python_callable=run_check_tennis_courts,
    pool="ydmap_baoti_browser",
    dag=dag,
)
