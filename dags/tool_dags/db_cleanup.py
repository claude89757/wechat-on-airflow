from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "start_date": pendulum.datetime(2022, 1, 1, tz="UTC"),
}

dag = DAG(
    "airflow_db_cleanup",
    default_args=default_args,
    description="Clean up Airflow database",
    schedule=timedelta(days=1),
    catchup=False,
    max_active_runs=1,
    tags=["通用工具"],
)

db_cleanup = BashOperator(
    task_id="db_cleanup",
    bash_command="""
set -euo pipefail
clean_before_timestamp="$(
  python -c 'import datetime; print((datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=180)).isoformat())'
)"
airflow db clean \
  --clean-before-timestamp "${clean_before_timestamp}" \
  --skip-archive \
  --error-on-cleanup-failure \
  --yes
""",
    dag=dag,
)
