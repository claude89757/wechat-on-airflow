import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.fsb_atuoshan_watcher import run_check_tennis_courts

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "start_date": datetime.datetime(2026, 8, 29, tzinfo=ZoneInfo("Asia/Shanghai")),
    "email_on_failure": False,
    "email_on_retry": False,
}

dag = DAG(
    "泛思博特安托山网球场巡检",
    default_args=DEFAULT_ARGS,
    description="泛思博特安托山网球场巡检 - Pospal平台",
    schedule=timedelta(seconds=30),
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
