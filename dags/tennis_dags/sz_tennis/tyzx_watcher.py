import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.venues.tyzx_watcher import run_check_tennis_courts

dag = DAG(
    "深圳市体育中心网球场巡检",
    default_args={
        "owner": "claude89757",
        "start_date": datetime.datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    },
    description="深圳市体育中心网球场巡检",
    schedule="*/1 * * * *",
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
