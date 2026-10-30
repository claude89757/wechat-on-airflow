import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.baoti_ydmap_watcher import run_check_tennis_courts

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "start_date": datetime.datetime(2026, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "宝安网球中心巡检",
    default_args=DEFAULT_ARGS,
    description="宝安网球中心（室外/室内/风雨场）巡检 - YDMap 树莓派浏览器采集",
    schedule=timedelta(minutes=2),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=["深圳"],
)

PythonOperator(
    task_id="check_tennis_courts",
    python_callable=run_check_tennis_courts,
    dag=dag,
)
