import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.fft_qianhai_watcher import run_check_tennis_courts

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "start_date": datetime.datetime(2026, 8, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    "email_on_failure": False,
    "email_on_retry": False,
}

dag = DAG(
    "FFTENNIS前海国际网球中心巡检",
    default_args=DEFAULT_ARGS,
    description="FFTENNIS前海国际网球中心巡检 - PosPal平台",
    schedule=timedelta(minutes=1),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=["深圳"],
)

check_tennis_courts = PythonOperator(
    task_id="check_tennis_courts",
    python_callable=run_check_tennis_courts,
    dag=dag,
)
