import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.dashahe_free_watcher import run_check_dashahe_free_courts

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "start_date": datetime.datetime(2026, 8, 16, tzinfo=ZoneInfo("Asia/Shanghai")),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "大沙河免费场巡检",
    default_args=DEFAULT_ARGS,
    description="南山文体通大沙河免费场巡检",
    schedule=timedelta(seconds=30),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=1),
    catchup=False,
    tags=["深圳", "免费场"],
)

PythonOperator(
    task_id="check_free_courts",
    python_callable=run_check_dashahe_free_courts,
    dag=dag,
)
