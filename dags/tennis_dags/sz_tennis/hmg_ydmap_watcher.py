import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.ftty_ydmap_watcher import run_check_hmg

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
    "黄木岗网球中心巡检",
    default_args=DEFAULT_ARGS,
    description="黄木岗网球中心网球场巡检 - YDMap 树莓派浏览器采集（ftty.ydmap.cn）",
    # ftty.ydmap.cn venues share one host: minutes 0/2/4 of each six.
    schedule="2-59/6 * * * *",
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=["深圳"],
)

PythonOperator(
    task_id="check_tennis_courts",
    python_callable=run_check_hmg,
    pool="ydmap_browser",
    dag=dag,
)
