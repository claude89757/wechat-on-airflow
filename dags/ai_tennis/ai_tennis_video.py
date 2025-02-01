#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
import time
from datetime import datetime, timedelta

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from smbclient import register_session, open_file

# 自定义库导入
from utils.wechat_channl import save_wx_file
from utils.wechat_channl import send_wx_msg
from utils.wechat_channl import send_wx_image
from utils.llm_channl import get_llm_response_with_image


DAG_ID = "ai_tennis_video"


def process_video_by_ai(input_video_path: str):
    """
    通过AI处理视频
    :param input_video_path:
    :return:
    """
    import cv2
    from ai_tennis.utils import read_video
    from ai_tennis.utils import save_video_to_images_with_sampling
    from ai_tennis.utils import find_frame_id_with_max_box
    from ai_tennis.player_traker import PlayerTracker
  
    # 读取视频, 采样间隔为3
    print(f"input_video_path: {input_video_path}")
    all_frames = read_video(input_video_path, sample_interval=3)

    # 显示最多的处理帧数
    print(f"all_frames: {len(all_frames)}")
    # 如果帧数大于300，则只取前300帧
    if len(all_frames) > 300:
        all_frames = all_frames[:300]
    print(f"all_frames: {len(all_frames)}")

    # 调整图像分辨率
    resized_frames = []
    target_width = 640  # 设置目标宽度
    for frame in all_frames:
        h, w = frame.shape[:2]
        ratio = target_width / w
        new_h = int(h * ratio)
        resized_frame = cv2.resize(frame, (target_width, new_h))
        resized_frames.append(resized_frame)
    video_frames = resized_frames

    # 初始化检测器并进行批量检测
    player_tracker = PlayerTracker(
        model_path='/opt/bitnami/airflow/dags/ai_tennis/models/yolov8x.pt',
        batch_size=4  # 设置批处理大小
    )
    player_detections = player_tracker.detect_frames(video_frames)

    # draw players bounding boxes
    output_video_frames = player_tracker.draw_bboxes(video_frames=video_frames, player_detections=player_detections)

    # find_frame_id_with_max_box
    max_box_frame_id = find_frame_id_with_max_box(player_detections[10:])  # 剔除前面几帧
    print(f"max_box_frame_id: {max_box_frame_id}")

    # Draw frame number on top left corner
    for i, frame in enumerate(output_video_frames):
        cv2.putText(frame, f"Frame: {i}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        if i >= max_box_frame_id:
            cv2.putText(frame, f"Frame: {i}*", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        else:
            cv2.putText(frame, f"Frame: {i}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    # Save image
    input_video_name = input_video_path.split('/')[-1].replace(".mp4", "")
    print(f"input_video_name: {input_video_name}")
    output_image_name = f"{input_video_name}_grid.jpg"
    print(f"output_image_name: {output_image_name}")
    output_image_path = save_video_to_images_with_sampling(output_video_frames, output_image_name,
                                                           max_box_frame_id, num_samples=10, target_size_kb=800)
    print("save image successfully")

    # send image to gpt
    text = "提供了一组网球运动员的动作照片\n" \
           "***回复格式示例***\n【动作】:xx\n【评分】:1~100分\n【优点】:xx\n【缺点】:xx\n\n" \
           "\n请根据[照片]，判断图片是哪一个网球动作（正手、单反、双反、正手切削、反手切削等），" \
           "并给这个网球动作打分, 打分的标准要参考图片动作和职业球员的标准动作的差距来确定, " \
           "并参考[回复格式示例]生成一份140字内的打分报告, 不要虚构数据和评语"
    response_msg = get_llm_response_with_image(user_question="请基于图片，给出网球动作的打分", image_path=output_image_path, system_prompt=text)

    return response_msg, output_image_path


def download_file_from_windows_server(remote_file_name: str, local_file_name: str, max_retries: int = 3, retry_delay: int = 5):
    """从SMB服务器下载文件
    
    Args:
        remote_file_name: 远程文件名
        local_file_name: 本地文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 本地文件路径
    """
    # 创建临时目录用于存储下载的文件
    temp_dir = "/tmp/video_downloads"
    os.makedirs(temp_dir, exist_ok=True)
    
    # 从Airflow变量获取配置
    windows_smb_dir = Variable.get("WINDOWS_SMB_DIR")
    windows_server_password = Variable.get("WINDOWS_SERVER_PASSWORD")

    # 解析UNC路径
    unc_parts = windows_smb_dir.strip("\\").split("\\")
    if len(unc_parts) < 3:
        raise ValueError(f"无效的SMB路径格式: {windows_smb_dir}。正确格式示例: \\\\server\\share\\path")

    # 将服务器名称中的下划线替换为点号
    server_name = unc_parts[0].replace("_", ".")    # 10.1.12.10
    share_name = unc_parts[1]                       # Users
    server_path = "/".join(unc_parts[2:])          # Administrator/Downloads
    print(f"server_name: {server_name}, share_name: {share_name}, server_path: {server_path}")

    # 注册SMB会话
    try:
        register_session(
            server=server_name,
            username="Administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径和本地路径
    remote_path = f"//{server_name}/{share_name}/{server_path}/{remote_file_name}"
    local_path = os.path.join(temp_dir, local_file_name)  # 修改为使用临时目录

    # 执行文件下载
    for attempt in range(max_retries):
        try:
            with open_file(remote_path, mode="rb") as remote_file:
                with open(local_path, "wb") as local_file:
                    while True:
                        data = remote_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        local_file.write(data)
            print(f"文件成功下载到: {os.path.abspath(local_path)}")
            
            # 验证文件大小不为0
            if os.path.getsize(local_path) == 0:
                raise Exception("下载的文件大小为0字节")
                
            return local_path  # 下载成功，返回本地文件路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次下载失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件下载失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常

    return local_path  # 返回完整的本地文件路径


def upload_file_to_windows_server(local_file_path: str, remote_file_name: str, max_retries: int = 3, retry_delay: int = 5):
    """上传文件到SMB服务器
    
    Args:
        local_file_path: 本地文件路径
        remote_file_name: 远程文件名
        max_retries: 最大重试次数，默认3次
        retry_delay: 重试间隔时间(秒)，默认5秒
    Returns:
        str: 远程文件的完整路径
    """
    # 从Airflow变量获取配置
    windows_smb_dir = Variable.get("WINDOWS_SMB_DIR")
    windows_server_password = Variable.get("WINDOWS_SERVER_PASSWORD")

    # 解析UNC路径
    unc_parts = windows_smb_dir.strip("\\").split("\\")
    if len(unc_parts) < 3:
        raise ValueError(f"无效的SMB路径格式: {windows_smb_dir}。正确格式示例: \\\\server\\share\\path")

    # 将服务器名称中的下划线替换为点号
    server_name = unc_parts[0].replace("_", ".")    # 10.1.12.10
    share_name = unc_parts[1]                       # Users
    server_path = "/".join(unc_parts[2:])          # Administrator/Downloads
    print(f"server_name: {server_name}, share_name: {share_name}, server_path: {server_path}")

    # 注册SMB会话
    try:
        register_session(
            server=server_name,
            username="Administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径
    remote_path = f"//{server_name}/{share_name}/{server_path}/{remote_file_name}"

    # 执行文件上传
    for attempt in range(max_retries):
        try:
            with open(local_file_path, "rb") as local_file:
                with open_file(remote_path, mode="wb") as remote_file:
                    while True:
                        data = local_file.read(8192)  # 分块读取大文件
                        if not data:
                            break
                        remote_file.write(data)
            
            print(f"文件成功上传到: {remote_path}")
            return f"C:/Users/Administrator/Downloads/{remote_file_name}"  # 返回Windows格式的路径
            
        except Exception as e:
            if attempt < max_retries - 1:  # 如果不是最后一次尝试
                print(f"第{attempt + 1}次上传失败: {str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)  # 等待一段时间后重试
            else:
                print(f"文件上传失败，已重试{max_retries}次: {str(e)}")
                raise  # 重试次数用完后，抛出异常


def process_ai_video(**context):
    """
    处理视频
    """
    # 当前消息
    current_message_data = context.get('dag_run').conf["current_message"]
    # 获取消息数据 
    sender = current_message_data.get('sender', '')  # 发送者ID
    room_id = current_message_data.get('roomid', '')  # 群聊ID
    msg_id = current_message_data.get('id', '')  # 消息ID
    content = current_message_data.get('content', '')  # 消息内容
    source_ip = current_message_data.get('source_ip', '')  # 获取源IP, 用于发送消息
    is_group = current_message_data.get('is_group', False)  # 是否群聊
    extra = current_message_data.get('extra', '')  # 消息extra字段

    # 保存视频到微信客户端侧
    save_dir = f"C:/Users/Administrator/Downloads/{msg_id}.mp4"
    video_file_path = save_wx_file(wcf_ip=source_ip, id=msg_id, save_file_path=save_dir)
    print(f"video_file_path: {video_file_path}")

    # 等待3秒
    time.sleep(3)

    # 下载视频到本地临时目录
    remote_file_name = os.path.basename(video_file_path)  # 使用os.path.basename获取文件名
    local_file_name = f"{msg_id}.mp4"
    local_file_path = download_file_from_windows_server(remote_file_name=remote_file_name, local_file_name=local_file_name)
    print(f"视频已下载到本地: {local_file_path}")

    # 处理视频
    start_time = time.time()
    start_msg = f"正在处理视频..."
    send_wx_msg(wcf_ip=source_ip, message=start_msg, receiver=room_id)

    response_msg, output_image_path = process_video_by_ai(local_file_path)
    print(f"response_msg: {response_msg}")
    print(f"output_image_path: {output_image_path}")

    end_time = time.time()
    end_msg = f"视频处理完成，耗时: {end_time - start_time:.2f}秒"
    send_wx_msg(wcf_ip=source_ip, message=end_msg, receiver=room_id)

    # 发送消息到微信
    send_wx_msg(wcf_ip=source_ip, message=response_msg, receiver=room_id)

    # 发送图片到微信: 先把图片上传到Windows服务器，然后从Windows服务器转发到微信
    remote_image_name = os.path.basename(output_image_path)
    print(f"remote_image_name: {remote_image_name}")
    print(f"output_image_path: {output_image_path}")
    windows_image_path = upload_file_to_windows_server(
        local_file_path=output_image_path,
        remote_file_name=remote_image_name
    )
    print(f"windows_image_path: {windows_image_path}")
    send_wx_image(wcf_ip=source_ip, image_path=windows_image_path, receiver=room_id)
    

# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={
        'owner': 'claude89757',
        'depends_on_past': False,
        'email_on_failure': False,
        'email_on_retry': False,
        'retries': 0,
        'retry_delay': timedelta(minutes=1),
    },
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=10,
    catchup=False,
    tags=['AI网球'],
    description='AI网球视频处理',
)


process_ai_video_task = PythonOperator(
    task_id='process_ai_video',
    python_callable=process_ai_video,
    provide_context=True,
    dag=dag,
)

process_ai_video_task
