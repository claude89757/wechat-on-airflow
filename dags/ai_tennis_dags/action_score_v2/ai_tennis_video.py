#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 标准库导入
import os
import time
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# 第三方库导入
import requests
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from smbclient import register_session, open_file

# 自定义库导入
from utils.wechat_channl import (
    save_wx_file,
    send_wx_msg, 
    send_wx_image
)

DAG_ID = "tennis_racket_speed_trajectory"


def track_racket_speed_trajectory(video_uri: str, output_video_path: str) -> str:
    """
    Tracks the tennis racket in a video, draws its center point trajectory,
    color-codes line segments based on speed, overlays the bounding box of 
    the racket, and saves the result as a new video.

    Parameters:
    -----------
    video_uri : str
        The path or URL of the input video.

    Returns:
    --------
    str
        The path to the saved output video.
    """
    from pillow_heif import register_heif_opener
    import cv2
    import numpy as np
    from utils.llm_channl import get_llm_response_with_image
    from vision_agent.tools import (
        extract_frames_and_timestamps,
        florence2_sam2_video_tracking,
        overlay_bounding_boxes,
        save_video,
        register_tool
    )
    from vision_agent.tools.planner_tools import judge_od_results

    # 注册HEIF图像格式支持
    register_heif_opener()

    print(f"开始处理视频: {video_uri}")
    # 1) Extract frames from the video (default fps=5).
    print("正在提取视频帧...")
    frame_data = extract_frames_and_timestamps(video_uri, fps=5)
    frames = [d["frame"] for d in frame_data]
    print(f"成功提取 {len(frames)} 帧")
    if not frames:
        raise ValueError("No frames extracted from video.")

    # 2) Detect the racket bounding boxes in each frame using florence2_sam2_video_tracking.
    print("正在检测网球拍并进行跟踪...")
    tracked_bboxes = florence2_sam2_video_tracking("tennis racket", frames)
    print(f"检测完成，共处理 {len(tracked_bboxes)} 帧")

    # We'll store center points and compute speeds.
    centers = []
    speeds = []
    prev_center = None

    # Because the bounding boxes are normalized, get the frame size for conversion.
    height, width = frames[0].shape[:2]
    print(f"视频尺寸: {width}x{height}")

    # 3) Convert bounding boxes to center points in pixel coordinates.
    print("正在计算网球拍中心点和速度...")
    for i, bboxes in enumerate(tracked_bboxes):
        if bboxes:
            bbox = bboxes[0]["bbox"]  # take the first bounding box
            x_min_norm, y_min_norm, x_max_norm, y_max_norm = bbox

            x_min = int(x_min_norm * width)
            y_min = int(y_min_norm * height)
            x_max = int(x_max_norm * width)
            y_max = int(y_max_norm * height)

            # Center point
            cx = (x_min + x_max) // 2
            cy = (y_min + y_max) // 2
            centers.append((cx, cy))

            # 4) Compute speed: distance between consecutive centers
            if prev_center is not None:
                dx = cx - prev_center[0]
                dy = cy - prev_center[1]
                speed = math.sqrt(dx*dx + dy*dy)
                speeds.append(speed)
                print(f"帧 {i}: 中心点 ({cx}, {cy}), 速度 {speed:.2f}")
            else:
                print(f"帧 {i}: 中心点 ({cx}, {cy}), 首个检测点")
            prev_center = (cx, cy)
        else:
            # If no detection on this frame, just append None
            centers.append(None)
            if prev_center is not None:
                speeds.append(0)
                print(f"帧 {i}: 未检测到网球拍")
            else:
                print(f"帧 {i}: 未检测到网球拍（首帧）")

    # Thresholds for color-coding
    if len(speeds) > 0:
        max_speed = max(speeds)
        slow_threshold = max_speed / 3
        medium_threshold = (2 * max_speed) / 3
        print(f"速度阈值 - 慢: <{slow_threshold:.2f}, 中: <{medium_threshold:.2f}, 快: >={medium_threshold:.2f}")
    else:
        slow_threshold = 0
        medium_threshold = 0
        print("未检测到有效的速度数据")

    # 创建一个透明轨迹图层，用于保存完整轨迹
    trail_layer = np.zeros((height, width, 4), dtype=np.uint8)
    
    # 定义渐变颜色映射函数
    def get_gradient_color(index, total, speed, max_speed):
        # 根据帧索引创建彩虹渐变色
        hue = int(180 * (index / total))
        
        # 提高饱和度和亮度，使颜色更加鲜艳
        saturation = min(255, int(230 + (speed / max_speed) * 25))
        value = min(255, int(230 + (speed / max_speed) * 25))
        
        # 转换HSV到BGR
        hsv_color = np.array([[[hue, saturation, value]]], dtype=np.uint8)
        bgr_color = cv2.cvtColor(hsv_color, cv2.COLOR_HSV2BGR)[0][0]
        
        return (int(bgr_color[0]), int(bgr_color[1]), int(bgr_color[2]))

    # 创建粒子效果函数
    def draw_particle_effect(image, center, color, radius=2, particles=6):
        for i in range(particles):
            angle = 2 * math.pi * i / particles
            offset_x = int(radius * 1.2 * math.cos(angle))
            offset_y = int(radius * 1.2 * math.sin(angle))
            particle_center = (center[0] + offset_x, center[1] + offset_y)
            
            # 画小圆点作为粒子
            cv2.circle(image, particle_center, radius // 2, color, -1)
            
            # 添加辉光效果
            cv2.circle(image, particle_center, radius, (*color, 100), 1)

    # 5) Create the output frames
    print("正在生成输出视频帧...")
    out_frames = []
    
    # 过滤掉None值，只保留有效的中心点
    valid_centers = [c for c in centers if c is not None]
    valid_count = len(valid_centers)
    
    for i, frame in enumerate(frames):
        drawn_frame = frame.copy()
        
        # 创建当前帧的轨迹层
        current_trail = trail_layer.copy()
        
        # 绘制完整轨迹历史
        valid_points_until_now = []
        valid_index = 0
        
        for j in range(i+1):
            if j < len(centers) and centers[j] is not None:
                valid_points_until_now.append(centers[j])
                valid_index += 1
        
        # 至少有两个点才能画线
        if len(valid_points_until_now) >= 2:
            # 绘制整个轨迹历史到trail_layer
            for k in range(1, len(valid_points_until_now)):
                prev_point = valid_points_until_now[k-1]
                curr_point = valid_points_until_now[k]
                
                # 根据在轨迹中的位置计算渐变颜色
                color = get_gradient_color(k, valid_count, 
                                         speeds[k-1] if k-1 < len(speeds) else 0, 
                                         max_speed if len(speeds) > 0 else 1)
                
                # 根据速度设置线宽
                if k-1 < len(speeds):
                    speed = speeds[k-1]
                    if speed < slow_threshold:
                        thickness = 1
                    elif speed < medium_threshold:
                        thickness = 2
                    else:
                        thickness = 3
                else:
                    thickness = 1
                
                # 在轨迹层上绘制线段
                cv2.line(current_trail, prev_point, curr_point, (*color, 255), thickness)
                
                # 添加高科技感发光效果 - 外发光
                glow_alpha = 150  # 提高发光透明度
                cv2.line(current_trail, prev_point, curr_point, (*color, glow_alpha), thickness+2)
                cv2.line(current_trail, prev_point, curr_point, (*color, glow_alpha//2), thickness+4)
                
                # 在连接点添加光晕效果 - 使用更小的点
                cv2.circle(current_trail, curr_point, thickness, (*color, 150), -1)
                cv2.circle(current_trail, curr_point, thickness+2, (*color, 80), -1)
        
        # 为当前位置添加特殊效果
        if i < len(centers) and centers[i] is not None:
            current_center = centers[i]
            
            # 获取当前速度级别
            if i > 0 and i-1 < len(speeds):
                speed = speeds[i-1]
                if speed < slow_threshold:
                    speed_level = "Slow"
                    glow_color = (0, 255, 0)  # 绿色
                elif speed < medium_threshold:
                    speed_level = "Medium"
                    glow_color = (0, 255, 255)  # 黄色
                else:
                    speed_level = "Fast"
                    glow_color = (0, 0, 255)  # 红色
            else:
                speed_level = "Initial"
                glow_color = (255, 255, 255)  # 白色
            
            # 绘制粒子效果
            draw_particle_effect(current_trail, current_center, glow_color)
            
            # 添加当前点的高科技感光晕
            radius = 3
            # 核心点
            cv2.circle(current_trail, current_center, radius, (*glow_color, 255), -1)
            # 内层辉光
            cv2.circle(current_trail, current_center, radius+2, (*glow_color, 200), 1)
            # 外层辉光
            cv2.circle(current_trail, current_center, radius+4, (*glow_color, 150), 1)
            # 最外层淡光
            cv2.circle(current_trail, current_center, radius+7, (*glow_color, 80), 1)
            
            # 添加十字准星效果
            line_length = 10
            # 水平线
            cv2.line(current_trail, 
                    (current_center[0] - line_length, current_center[1]),
                    (current_center[0] + line_length, current_center[1]),
                    (*glow_color, 220), 1)
            # 垂直线
            cv2.line(current_trail, 
                    (current_center[0], current_center[1] - line_length),
                    (current_center[0], current_center[1] + line_length),
                    (*glow_color, 220), 1)
                    
            # 添加角度标记 - 更炫酷
            angle_length = 6
            for ang in [45, 135, 225, 315]:
                rad = math.radians(ang)
                end_x = current_center[0] + int(angle_length * math.cos(rad))
                end_y = current_center[1] + int(angle_length * math.sin(rad))
                cv2.line(current_trail, current_center, (end_x, end_y), (*glow_color, 180), 1)
            
            print(f"帧 {i}: 绘制 {speed_level} 速度特效 在位置 {current_center}")

        # Overlays the bounding boxes for clarity. We must pass normalized coordinates.
        # Rebuild a list of bboxes for overlay. We only overlay the known bounding box (if any).
        if tracked_bboxes[i]:
            overlay_input = []
            for item in tracked_bboxes[i]:
                overlay_input.append({
                    "score": item.get("score", 1.0),
                    "label": item.get("label", "tennis_racket"),
                    "bbox": item["bbox"]  # normalized
                })
            drawn_frame = overlay_bounding_boxes(drawn_frame, overlay_input)

        # 将轨迹层与原始帧融合
        # 直接使用前3个通道，无需颜色空间转换
        trail_bgr = current_trail[:,:,0:3]
        # 使用alpha通道作为mask
        alpha = current_trail[:,:,3:4] / 255.0
        # 融合图像
        drawn_frame = (1 - alpha) * drawn_frame + alpha * trail_bgr
        drawn_frame = drawn_frame.astype(np.uint8)
        
        # 更新持久化的轨迹层
        trail_layer = current_trail.copy()

        # Create a speed legend with gradient background - 更现代的风格
        legend_height = 30
        legend_width = 400
        legend_bg = np.zeros((legend_height, legend_width, 3), dtype=np.uint8)
        
        # 创建更精致的渐变背景
        for x in range(legend_width):
            hue = int(180 * (x / legend_width))
            # 更细腻的渐变，使用高饱和度
            cv2.line(legend_bg, (x, 0), (x, legend_height), (hue, 255, 255), 1)
        
        legend_bg = cv2.cvtColor(legend_bg, cv2.COLOR_HSV2BGR)
        
        # 添加半透明黑色背景，提高可读性
        overlay = legend_bg.copy()
        cv2.rectangle(overlay, (0, 0), (legend_width, legend_height), (0, 0, 0), -1)
        legend_bg = cv2.addWeighted(overlay, 0.5, legend_bg, 0.8, 0)  # 调整透明度比例
        
        # 使用更现代的文字样式
        font_scale = 0.4
        font_thickness = 1
        cv2.putText(legend_bg, "SPEED TRACK", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
        cv2.putText(legend_bg, "SLOW", (140, 20), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
        cv2.putText(legend_bg, "MEDIUM", (220, 20), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
        cv2.putText(legend_bg, "FAST", (320, 20), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
        
        # 添加高亮边框和分隔标记
        cv2.rectangle(legend_bg, (0, 0), (legend_width-1, legend_height-1), (255, 255, 255), 1)  # 白色边框
        cv2.line(legend_bg, (130, 5), (130, 25), (255, 255, 255), 1)
        cv2.line(legend_bg, (210, 5), (210, 25), (255, 255, 255), 1)
        cv2.line(legend_bg, (310, 5), (310, 25), (255, 255, 255), 1)
        
        # 将图例放到画面上
        drawn_frame[10:10+legend_height, 10:10+legend_width] = legend_bg

        out_frames.append(drawn_frame)

    # 6) Save the resulting frames as a new video.
    print(f"正在保存输出视频到: {output_video_path}")
    output_path = save_video(out_frames, fps=5, output_video_path=output_video_path)
    print(f"视频处理完成，已保存到: {output_path}")

    return output_path


def download_file_from_windows_server(server_ip: str, remote_file_name: str, local_file_name: str, max_retries: int = 3, retry_delay: int = 5):
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
    windows_server_password = Variable.get("AI_TENNIS_WINDOWS_SERVER_PASSWORD")

    # 注册SMB会话
    try:
        register_session(
            server=server_ip,
            username="administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径和本地路径
    remote_path = f"//{server_ip}/Users/Administrator/Downloads/{remote_file_name}"
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


def upload_file_to_windows_server(server_ip: str, local_file_path: str, remote_file_name: str, max_retries: int = 3, retry_delay: int = 5):
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
    windows_server_password = Variable.get("AI_TENNIS_WINDOWS_SERVER_PASSWORD")

    # 注册SMB会话
    try:
        register_session(
            server=server_ip,
            username="administrator",
            password=windows_server_password
        )
    except Exception as e:
        print(f"连接服务器失败: {str(e)}")
        raise

    # 构建远程路径
    remote_path = f"//{server_ip}/Users/Administrator/Downloads/{remote_file_name}"

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
    save_dir = f"C:/Users/Administrator/Downloads/"
    video_file_path = save_wx_file(wcf_ip=source_ip, id=msg_id, save_file_path=save_dir)
    print(f"video_file_path: {video_file_path}")

    # 等待3秒
    time.sleep(3)

    # 下载视频到本地临时目录
    remote_file_name = os.path.basename(video_file_path)  # 使用os.path.basename获取文件名
    local_file_name = f"{msg_id}.mp4"
    local_file_path = download_file_from_windows_server(server_ip=source_ip, remote_file_name=remote_file_name, local_file_name=local_file_name)
    print(f"视频已下载到本地: {local_file_path}")

    # 处理视频
    start_time = time.time()
    start_msg = f"Zacks 正在努力逐帧分析、疯狂动脑中，等我1分钟！\n（15秒的视频分析会更快哦）"
    send_wx_msg(wcf_ip=source_ip, message=start_msg, receiver=room_id)

    output_image_path = local_file_path.replace(".mp4", "_output.mp4")
    output_image_path = track_racket_speed_trajectory(local_file_path, output_image_path)
    print(f"output_image_path: {output_image_path}")

    end_time = time.time()
    end_msg = f"视频分析完成，耗时: {end_time - start_time:.2f}秒"
    send_wx_msg(wcf_ip=source_ip, message=end_msg, receiver=room_id)

    # 发送图片到微信: 先把图片上传到Windows服务器，然后从Windows服务器转发到微信
    remote_image_name = os.path.basename(output_image_path)
    print(f"remote_image_name: {remote_image_name}")
    print(f"output_image_path: {output_image_path}")
    windows_image_path = upload_file_to_windows_server(
        server_ip=source_ip,
        local_file_path=output_image_path,
        remote_file_name=remote_image_name
    )
    print(f"windows_image_path: {windows_image_path}")
    send_wx_image(wcf_ip=source_ip, image_path=windows_image_path, receiver=room_id)
    

# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    max_active_runs=10,
    catchup=False,
    tags=['AI网球'],
    description='网球拍轨迹分析',
)


process_ai_video_task = PythonOperator(
    task_id='process_ai_video',
    python_callable=process_ai_video,
    provide_context=True,
    dag=dag,
)

process_ai_video_task
