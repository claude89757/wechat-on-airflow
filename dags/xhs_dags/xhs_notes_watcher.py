#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

from utils.xhs_appium import XHSOperator


def collect_xhs_notes(**context) -> None:
    """
    收集小红书笔记
    
    从小红书搜索指定关键词的笔记并缓存到Airflow变量中。
    
    Args:
        **context: Airflow上下文参数字典
    
    Returns:
        None
    """
    # 获取关键词，默认为"AI客服"
    keyword = (context['dag_run'].conf.get('keyword', '网球') 
              if context['dag_run'].conf 
              else '网球')
    
    # 获取最大收集笔记数，默认为5
    max_notes = (context['dag_run'].conf.get('max_notes', 5)
                if context['dag_run'].conf
                else 5)
    
    # 获取Appium服务器URL
    appium_server_url = Variable.get("APPIUM_SERVER_URL", "http://localhost:4723")
    
    print(f"开始收集关键词 '{keyword}' 的小红书笔记...")
    
    try:
        # 初始化小红书操作器
        xhs = XHSOperator(appium_server_url=appium_server_url, force_app_launch=True)
        
        # # 检查是否在首页
        # if not xhs.is_at_xhs_home_page():
        #     xhs.return_to_home_page()
        
        # 收集笔记
        notes = xhs.collect_notes_by_keyword(
            keyword=keyword,
            max_notes=max_notes
        )
        
        if not notes:
            print(f"未找到关于 '{keyword}' 的笔记")
            return
            
        # 打印收集结果
        print("\n收集完成!")
        print(f"共收集到 {len(notes)} 条笔记:")
        for note in notes:
            print(note)

        # 缓存数据到Airflow变量
        date_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        cache_key = f"XHS_NOTES_{keyword}"
        Variable.set(cache_key, notes, serialize_json=True, description=f"小红书笔记缓存: {keyword} at {date_str}")
            
    except Exception as e:
        error_msg = f"收集小红书笔记失败: {str(e)}"
        print(error_msg)
        raise
    finally:
        # 确保关闭小红书操作器
        if 'xhs' in locals():
            xhs.close()


def classify_notes_by_llm(**context) -> None:
    """
    使用大模型对收集的小红书笔记进行分类
    
    Args:
        **context: Airflow上下文参数字典
    
    Returns:
        None
    """
    from utils.llm_channl import get_llm_response
    
    # 获取关键词
    keyword = (context['dag_run'].conf.get('keyword', '网球') 
              if context['dag_run'].conf 
              else '网球')
    
    # 从Airflow变量中获取缓存的笔记
    cache_key = f"XHS_NOTES_{keyword}"
    notes = Variable.get(cache_key, deserialize_json=True)
    
    if not notes:
        print(f"未找到关于 '{keyword}' 的缓存笔记")
        return
        
    # 构建系统提示词
    system_prompt = """你是一个专业的社交媒体内容分析专家。请帮我分析小红书笔记的性质，将其分为以下两类：
    1. 营销笔记：
       - 明显的广告/推销意图
       - 过分夸张的效果描述
       - 大量营销关键词(如"专柜价"、"优惠"、"推荐"等)
       - 虚假或夸大的用户体验
       - 带有明显的导流或引导购买意图
    
    2. 真实笔记：
       - 真实的个人体验分享
       - 客观的描述和评价
       - 包含具体细节和真实场景
       - 有真实的情感表达
       - 可能包含优缺点的平衡评价
    
    请仔细分析笔记的内容、语气和表达方式，给出分类结果和简要分析理由。
    
    请按以下格式输出：
    {
        "category": "营销笔记/真实笔记",
        "reason": "分类理由",
        "confidence": "高/中/低"
    }
    """
    
    classified_results = []
    
    # 逐条分析笔记
    for note in notes:
        try:
            # 构建问题
            question = f"""请分析这条小红书笔记的性质：
            标题：{note.get('title', '')}
            内容：{note.get('content', '')}
            """
            
            # 调用大模型
            response = get_llm_response(
                user_question=question,
                system_prompt=system_prompt,
                model_name="gpt-4o-mini"
            )
            
            # 解析响应
            result = json.loads(response)
            result['note'] = note
            classified_results.append(result)
            
        except Exception as e:
            print(f"分析笔记失败: {str(e)}")
            continue
    
    # 缓存分类结果
    cache_key = f"XHS_NOTES_CLASSIFIED_{keyword}"
    Variable.set(
        cache_key, 
        classified_results, 
        serialize_json=True,
        description=f"小红书笔记分类结果: {keyword} at {datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    
    # 打印分类结果统计
    marketing_count = sum(1 for r in classified_results if r['category'] == '营销笔记')
    genuine_count = sum(1 for r in classified_results if r['category'] == '真实笔记')
    print(f"\n分类完成！共分析 {len(classified_results)} 条笔记:")
    print(f"营销笔记: {marketing_count} 条")
    print(f"真实笔记: {genuine_count} 条")

def publish_analysis_note(**context) -> None:
    """
    将分类分析结果整理成小红书笔记并发布
    
    Args:
        **context: Airflow上下文参数字典
    
    Returns:
        None
    """
    from utils.llm_channl import get_llm_response
    from utils.xhs_appium import XHSOperator
    
    # 获取关键词
    keyword = (context['dag_run'].conf.get('keyword', '网球') 
              if context['dag_run'].conf 
              else '网球')
    
    # 获取分类结果
    cache_key = f"XHS_NOTES_CLASSIFIED_{keyword}"
    classified_results = Variable.get(cache_key, deserialize_json=True)
    
    if not classified_results:
        print(f"未找到关于 '{keyword}' 的分类结果")
        return
        
    # 构建系统提示词
    system_prompt = f"""你是一个专业的小红书内容创作专家。请基于我提供的笔记分析数据，撰写一篇吸引人的小红书笔记。要求：
    1. 标题要简短有力，吸引眼球
    2. 内容要客观真实，以数据说话
    3. 语气要轻松自然，符合小红书风格
    4. 要突出对"{keyword}"相关内容的真伪识别价值
    5. 可以用emoji表情，但不要过度使用
    6. 总字数控制在1000字以内
    7. 分段要清晰，可以用序号或符号分隔
    
    请按以下格式输出：
    {
        "title": "标题",
        "content": "正文内容"
    }
    """
    
    # 构建输入数据
    stats = {
        "total": len(classified_results),
        "marketing": sum(1 for r in classified_results if r['category'] == '营销笔记'),
        "genuine": sum(1 for r in classified_results if r['category'] == '真实笔记'),
        "examples": {
            "marketing": [r for r in classified_results if r['category'] == '营销笔记'][:2],
            "genuine": [r for r in classified_results if r['category'] == '真实笔记'][:2]
        }
    }
    
    question = f"""请基于以下数据撰写一篇小红书笔记：
    关键词：{keyword}
    分析笔记总数：{stats['total']}
    营销笔记数量：{stats['marketing']}
    真实笔记数量：{stats['genuine']}
    
    典型营销笔记特征：
    {json.dumps(stats['examples']['marketing'], ensure_ascii=False, indent=2)}
    
    典型真实笔记特征：
    {json.dumps(stats['examples']['genuine'], ensure_ascii=False, indent=2)}
    """
    
    try:
        # 调用大模型生成笔记
        response = get_llm_response(
            user_question=question,
            system_prompt=system_prompt,
            model_name="gpt-4o-mini"
        )
        
        note_data = json.loads(response)
        
        # 发布笔记
        appium_server_url = Variable.get("APPIUM_SERVER_URL", "http://localhost:4723")
        xhs = XHSOperator(appium_server_url=appium_server_url, force_app_launch=True)
        
        try:
            # xhs.publish_note(
            #     title=note_data['title'],
            #     content=note_data['content']
            # )
            print(f"笔记发布成功！")
            print(f"标题: {note_data['title']}")
            print(f"内容: {note_data['content']}")
            
        finally:
            xhs.close()
            
    except Exception as e:
        error_msg = f"发布分析笔记失败: {str(e)}"
        print(error_msg)
        raise


# DAG 定义
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    dag_id='小红书笔记收集巡检',
    default_args=default_args,
    description='定时收集小红书笔记',
    schedule_interval='0 10,15,20 * * *',  # 每天10点、15点和20点执行
    tags=['小红书'],
    catchup=False,
)

collect_notes_task = PythonOperator(
    task_id='collect_xhs_notes',
    python_callable=collect_xhs_notes,
    provide_context=True,
    dag=dag,
)

classify_notes_task = PythonOperator(
    task_id='classify_notes_by_llm',
    python_callable=classify_notes_by_llm,
    provide_context=True,
    dag=dag,
)

publish_analysis_task = PythonOperator(
    task_id='publish_analysis_note',
    python_callable=publish_analysis_note,
    provide_context=True,
    dag=dag,
)

# 设置任务依赖关系
collect_notes_task >> classify_notes_task >> publish_analysis_task
