import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.szw_watcher import check_and_notify_for_day

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "start_date": datetime.datetime(2026, 8, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    "大湾区网球场巡检",
    default_args=DEFAULT_ARGS,
    description="大湾区网球场巡检（并行多天）",
    schedule=timedelta(minutes=1),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    catchup=False,
    tags=["深圳"],
)

# The upstream API exposes today plus the next two calendar days.
for day_offset in range(3):
    PythonOperator(
        task_id=f"check_and_notify_day_{day_offset}",
        python_callable=check_and_notify_for_day,
        op_kwargs={"day_offset": day_offset, "venue_key": "gba"},
        dag=dag,
    )
