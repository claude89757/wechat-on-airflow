#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.models.variable import Variable

from utils.xhs_appium import XHSOperator
from utils.wechat_channl import send_wx_msg


def collect_xhs_notes(**context) -> None:
    """
    收集小红书笔记
    
    从小红书搜索指定关键词的笔记并通过xcom传递给下一个任务。
    
    Args:
        **context: Airflow上下文参数字典
    
    Returns:
        None
    """
    # 获取触发消息的微信群ID和来源IP
    message_data = context['dag_run'].conf.get('current_message', {})
    group_id = message_data.get('roomid')
    source_ip = message_data.get('source_ip')
    
    # 获取关键词，默认为"AI客服"
    keyword = (context['dag_run'].conf.get('keyword', '深圳网球') 
              if context['dag_run'].conf 
              else '深圳网球')
    
    # 发送开始搜索的提醒
    if group_id and source_ip:
        send_wx_msg(
            wcf_ip=source_ip,
            message=f"🔍 正在搜索「{keyword}」的最新真实笔记，请稍等~",
            receiver=group_id
        )

    # 获取最大收集笔记数，默认为5
    max_notes = (context['dag_run'].conf.get('max_notes', 10)
                if context['dag_run'].conf
                else 10)
    
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
            max_notes=max_notes,
            filters={'sort_by': '最新', 'note_type': '图文'},
            include_comments=False
        )
        
        if not notes:
            print(f"未找到关于 '{keyword}' 的笔记")
            return
            
        # 过滤标签
        for note in notes:
            if 'content' in note:
                # 将内容按空格分割，过滤掉以#开头的部分
                content = note['content']
                words = content.split()
                filtered_words = [word for word in words if not word.startswith('#')]
                # 重新组合内容
                note['content'] = ' '.join(filtered_words)
        
        # 打印收集结果
        print("\n收集完成!")
        print(f"共收集到 {len(notes)} 条笔记:")
        for note in notes:
            print(note)

        # 使用固定的XCom key
        task_instance = context['task_instance']
        task_instance.xcom_push(key="collected_notes", value=notes)
            
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
    keyword = (context['dag_run'].conf.get('keyword', '深圳网球') 
              if context['dag_run'].conf 
              else '深圳网球')
    
    # 从XCom获取笔记数据，使用固定key
    task_instance = context['task_instance']
    notes = task_instance.xcom_pull(
        task_ids='collect_xhs_notes',
        key="collected_notes"
    )
    
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
    print(f"开始分析 {len(notes)} 条笔记")
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
    
    # 使用固定的XCom key传递分类结果
    task_instance.xcom_push(
        key="classified_notes",
        value=classified_results
    )
    
    # 打印分类结果统计
    marketing_count = sum(1 for r in classified_results if r['category'] == '营销笔记')
    genuine_count = sum(1 for r in classified_results if r['category'] == '真实笔记')
    print(f"\n分类完成！共分析 {len(classified_results)} 条笔记:")
    print(f"营销笔记: {marketing_count} 条")
    print(f"真实笔记: {genuine_count} 条")

def summarize_notes(**context) -> None:
    """
    总结和摘要真实的笔记信息，并推送到微信群中
    每个笔记用一句话总结，分批处理后汇总展示
    
    Args:
        **context: Airflow上下文参数字典
    
    Returns:
        None
    """
    from utils.llm_channl import get_llm_response
    from utils.wechat_channl import send_wx_msg
    
    # 获取关键词
    keyword = (context['dag_run'].conf.get('keyword', '深圳网球') 
              if context['dag_run'].conf 
              else '深圳网球')
    
    # 获取触发消息的微信群ID和来源IP
    message_data = context['dag_run'].conf.get('current_message', {})
    group_id = message_data.get('roomid')
    source_ip = message_data.get('source_ip')
    
    if not group_id or not source_ip:
        print("未提供微信群ID或来源IP，无法推送消息")
        return
    
    # 从XCom获取分类结果，使用固定key
    task_instance = context['task_instance']
    classified_results = task_instance.xcom_pull(
        task_ids='classify_notes_by_llm',
        key="classified_notes"
    )
    
    if not classified_results:
        print(f"未找到关于 '{keyword}' 的分类结果")
        return
    
    # 筛选真实笔记和营销笔记
    genuine_notes = [
        result['note'] for result in classified_results 
        if result['category'] == '真实笔记'
    ]
    marketing_notes_count = sum(1 for result in classified_results 
                              if result['category'] == '营销笔记')
    
    if not genuine_notes:
        return "未发现关于 '{keyword}' 的真实笔记"
    
    BATCH_SIZE = 5  # 每批处理5条笔记
    
    # 修改系统提示词
    system_prompt = """你是一个专业的内容总结专家。请用一句话总结每条小红书笔记的核心内容。
    要求：
    1. 每条笔记的总结不超过15个字
    2. 突出笔记的关键信息和独特见解
    3. 保持客观中立的语气
    4. 按照以下格式输出：
    {
        "summaries": [
            {"summary": "一句话总结", "url": "笔记链接"}
        ]
    }
    """
    all_summaries = []
    
    # 分批处理笔记
    for i in range(0, len(genuine_notes), BATCH_SIZE):
        batch_notes = genuine_notes[i:i + BATCH_SIZE]
        
        # 构建当前批次的笔记内容
        notes_content = []
        for note in batch_notes:
            notes_content.append(f"""
标题：{note.get('title', '')}
内容：{note.get('content', '')}
链接：{note.get('url', '未知')}
            """)
        
        # 调用大模型生成当前批次的总结
        question = f"请分别用一句话总结以下{len(notes_content)}条小红书笔记：\n" + "\n---\n".join(notes_content)
        
        summary_response = get_llm_response(
            user_question=question,
            system_prompt=system_prompt,
            model_name="gpt-4o-mini"
        )
        
        # 解析JSON响应并合并结果
        batch_summary_data = json.loads(summary_response)
        all_summaries.extend(batch_summary_data['summaries'])
        
        # 打印进度
        print(f"已完成 {min(i + BATCH_SIZE, len(genuine_notes))}/{len(genuine_notes)} 条笔记的总结")
    
    # 构建最终消息
    message_parts = [
        f"🔍 {keyword} - 最新笔记速览\n",
        f" 统计信息：",
        f"• 总计：{len(classified_results)}条笔记",
        f"• 真实：{len(genuine_notes)}条",
        f"• 过滤：{marketing_notes_count}条营销笔记\n",
        f" 笔记概要：",
    ]
    
    for idx, item in enumerate(all_summaries, 1):
        message_parts.append(f"{idx}. {item['summary']}")
        message_parts.append(f"   👉 {item['url']}\n")
    
    message = "\n".join(message_parts)
    
    # 使用send_wx_msg发送消息
    send_wx_msg(
        wcf_ip=source_ip,
        message=message,
        receiver=group_id
    )
    print(f"已将所有笔记总结推送到微信群")
        

# DAG 定义
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
}

dag = DAG(
    dag_id='xhs_notes_watcher',
    default_args=default_args,
    description='小红书笔记收集巡检',
    schedule_interval=None, 
    max_active_runs=1,
    tags=['小红书'],
    catchup=False,
)

collect_notes_task = PythonOperator(
    task_id='collect_xhs_notes',
    python_callable=collect_xhs_notes,
    provide_context=True,
    retries=2,
    retry_delay=timedelta(seconds=3),
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
    python_callable=summarize_notes,
    provide_context=True,
    dag=dag,
)

# 设置任务依赖关系
collect_notes_task >> classify_notes_task >> publish_analysis_task
