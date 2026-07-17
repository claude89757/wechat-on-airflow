from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.proxy_tools.ydmap_https_proxy_watcher import task_check_proxies

DEFAULT_ARGS = {
    "owner": "claude89757",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(minutes=60),
}

dag = DAG(
    dag_id="HTTPS可用代理巡检_ydmap",
    default_args=DEFAULT_ARGS,
    description="A DAG to check and update HTTPS proxies",
    schedule="*/5 * * * *",
    start_date=datetime(2024, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    max_active_runs=1,
    catchup=False,
    tags=["proxy", "ydmap"],
)

check_proxies = PythonOperator(
    task_id="check_proxies",
    python_callable=task_check_proxies,
    dag=dag,
)
