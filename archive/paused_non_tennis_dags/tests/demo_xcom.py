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
    tags=['测试示例'],
    catchup=False
)

# 定义Python函数
def task1_function(**context):
    """生成一些数据并通过XCom传递"""
    data = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'value': 100
    }
    context['task_instance'].xcom_push(key='task1_data', value=data)
    print("执行任务1，生成数据:", data)
    return "任务1完成"

def task2_function(**context):
    """从task1获取数据并处理"""
    task1_data = context['task_instance'].xcom_pull(
        task_ids='task1', 
        key='task1_data'
    )
    processed_value = task1_data['value'] * 2
    context['task_instance'].xcom_push(
        key='task2_result', 
        value=processed_value
    )
    print(f"执行任务2，处理数据: {task1_data} -> {processed_value}")
    return "任务2完成"

def task3_function(**context):
    """从task1获取数据并进行不同的处理"""
    task1_data = context['task_instance'].xcom_pull(
        task_ids='task1', 
        key='task1_data'
    )
    processed_value = task1_data['value'] + 50
    context['task_instance'].xcom_push(
        key='task3_result', 
        value=processed_value
    )
    print(f"执行任务3，处理数据: {task1_data} -> {processed_value}")
    return "任务3完成"

def task4_function(**context):
    """获取task2和task3的结果并综合处理"""
    task2_result = context['task_instance'].xcom_pull(
        task_ids='task2', 
        key='task2_result'
    )
    task3_result = context['task_instance'].xcom_pull(
        task_ids='task3', 
        key='task3_result'
    )
    final_result = task2_result + task3_result
    print(f"任务4最终结果: {final_result}")
    return f"任务4完成，最终结果: {final_result}"

# 创建任务
task1 = PythonOperator(
    task_id='task1',
    python_callable=task1_function,
    provide_context=True,
    dag=dag,
)

task2 = PythonOperator(
    task_id='task2',
    python_callable=task2_function,
    provide_context=True,
    dag=dag,
)

task3 = PythonOperator(
    task_id='task3',
    python_callable=task3_function,
    provide_context=True,
    dag=dag,
)

task4 = PythonOperator(
    task_id='task4',
    python_callable=task4_function,
    provide_context=True,
    dag=dag,
)

# 设置任务依赖关系
task1 >> [task2, task3] >> task4
