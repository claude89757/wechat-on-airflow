from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

# 定义默认参数
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# 创建 DAG 实例
dag = DAG(
    'simple_workflow_example',
    default_args=default_args,
    description='一个简单的工作流示例',
    schedule_interval=timedelta(days=1),
    catchup=False
)

# 定义Python函数
def task1_function():
    print("执行任务1")
    return "任务1完成"

def task2_function():
    print("执行任务2")
    return "任务2完成"

def task3_function():
    print("执行任务3")
    return "任务3完成"

# 创建任务
task1 = PythonOperator(
    task_id='task1',
    python_callable=task1_function,
    dag=dag,
)

task2 = PythonOperator(
    task_id='task2',
    python_callable=task2_function,
    dag=dag,
)

task3 = PythonOperator(
    task_id='task3',
    python_callable=task3_function,
    dag=dag,
)

task4 = BashOperator(
    task_id='task4',
    bash_command='echo "任务4执行完成"',
    dag=dag,
)

# 设置任务依赖关系
task1 >> [task2, task3] >> task4
