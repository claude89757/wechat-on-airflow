from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from wechat_airflow.maintenance.zacks_phone_reboot import (
    reboot_zacks_phone as reboot_zacks_phone_callable,
)
from wechat_airflow.maintenance.zacks_phone_reboot import (
    resolve_zacks_device_config as resolve_zacks_device_config_callable,
)
from wechat_airflow.maintenance.zacks_phone_reboot import (
    wait_until_phone_ready as wait_until_phone_ready_callable,
)

DAG_ID = "zacks_phone_daily_reboot"

with DAG(
    dag_id=DAG_ID,
    default_args={
        "owner": "claude89757",
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    description="每天定时重启 zacks 手机",
    schedule="0 5 * * *",
    start_date=datetime(2025, 4, 13, tzinfo=ZoneInfo("Asia/Shanghai")),
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=45),
    catchup=False,
    tags=["个人微信", "zacks", "运维"],
) as dag:
    resolve_zacks_device_config = PythonOperator(
        task_id="resolve_zacks_device_config",
        python_callable=resolve_zacks_device_config_callable,
    )
    reboot_zacks_phone = PythonOperator(
        task_id="reboot_zacks_phone",
        python_callable=reboot_zacks_phone_callable,
    )
    wait_until_phone_ready = PythonOperator(
        task_id="wait_until_phone_ready",
        python_callable=wait_until_phone_ready_callable,
    )

    resolve_zacks_device_config >> reboot_zacks_phone >> wait_until_phone_ready
