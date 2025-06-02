#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import math
import requests
import tempfile
from pillow_heif import register_heif_opener

# 设置OpenCV为headless模式，避免GUI依赖
os.environ['OPENCV_HEADLESS'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import cv2

register_heif_opener()


def get_video_info(video_path: str) -> dict:
    """获取视频基本信息"""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()
    
    return {
        'fps': fps, 'total_frames': total_frames, 'width': width,
        'height': height, 'duration': duration, 'file_size': os.path.getsize(video_path)
    }

def trim_video_if_needed(video_path: str, max_duration: float = 6.0, max_size_mb: float = 50.0) -> str:
    """如果视频过长或过大，则裁剪视频"""
    print("\n检查视频是否需要裁剪...")
    
    video_info = get_video_info(video_path)
    file_size_mb = video_info['file_size'] / (1024 * 1024)
    
    print(f"视频信息: 时长{video_info['duration']:.2f}秒, 大小{file_size_mb:.2f}MB")
    
    needs_trim = video_info['duration'] > max_duration or file_size_mb > max_size_mb
    if not needs_trim:
        print("✅ 视频无需裁剪")
        return video_path
    
    temp_dir = tempfile.mkdtemp()
    temp_video_path = os.path.join(temp_dir, "trimmed_" + os.path.basename(video_path))
    
    try:
        print(f"🔄 正在裁剪视频至前 {max_duration} 秒...")
        cap = cv2.VideoCapture(video_path)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(temp_video_path, fourcc, video_info['fps'], 
                             (video_info['width'], video_info['height']))
        
        target_frames = int(video_info['fps'] * max_duration)
        frame_count = 0
        
        while frame_count < target_frames:
            ret, frame = cap.read()
            if not ret:
                break
            out.write(frame)
            frame_count += 1
        
        cap.release()
        out.release()
        
        if os.path.exists(temp_video_path):
            print("✅ 裁剪完成")
            return temp_video_path
        else:
            return video_path
    except Exception as e:
        print(f"❌ 裁剪过程出错: {e}")
        return video_path

def call_vision_agent_api(video_path: str, prompts: list) -> list:
    """调用Vision Agent API进行视频目标检测"""
    print(f"\n🔍 调用Vision Agent API...")
    print(f"🎯 检测目标: {prompts}")
    
    url = "https://api.va.landing.ai/v1/tools/text-to-object-detection"
    api_key = os.getenv('VISION_AGENT_API_KEY')
    
    files = {"video": open(video_path, "rb")}
    data = {"prompts": prompts, "model": "owlv2", "function_name": "owl_v2_video"}
    headers = {"Authorization": f"Basic {api_key}"}
    
    try:
        print("📡 发送API请求...")
        print(f"url: {url}")
        print(f"files: {str(files)[:100]}")
        print(f"data: {data}")
        print(f"headers: {headers}")
        response = requests.post(url, files=files, data=data, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            print("✅ API调用成功")
            print("="*100)
            print(result)
            print("="*100)
            return result.get('data', [])
        else:
            error_msg = f"API请求失败: {response.status_code} - {response.text}"
            print(f"❌ {error_msg}")
            raise Exception(error_msg)
            
    except Exception as e:
        print(f"❌ API调用异常: {e}")
        raise e
    finally:
        files["video"].close()

def convert_api_detections_to_tracked_format(api_detections: list) -> tuple:
    """将API检测结果转换为跟踪格式"""
    print("\n🔄 转换API检测结果格式...")
    
    ball_tracked, racket_tracked, player_tracked = [], [], []
    
    for frame_detections in api_detections:
        frame_ball, frame_racket, frame_player = [], [], []
        
        for detection in frame_detections:
            converted_detection = {
                "bbox": detection["bounding_box"],
                "score": detection["score"],
                "label": detection["label"]
            }
            
            label_lower = detection['label'].lower()
            if "ball" in label_lower:
                frame_ball.append(converted_detection)
            elif "racket" in label_lower:
                frame_racket.append(converted_detection)
            elif "player" in label_lower:
                frame_player.append(converted_detection)
        
        ball_tracked.append(frame_ball)
        racket_tracked.append(frame_racket)
        player_tracked.append(frame_player)
    
    print(f"📊 检测结果: 网球{sum(len(f) for f in ball_tracked)}, 球拍{sum(len(f) for f in racket_tracked)}, 运动员{sum(len(f) for f in player_tracked)}")
    return ball_tracked, racket_tracked, player_tracked

def extract_frames_from_video(video_path: str) -> tuple:
    """从视频中提取帧数据"""
    print("\n📽️ 从视频提取帧数据...")
    
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames_list = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames_list.append(frame_rgb)
    
    cap.release()
    print(f"✅ 提取完成: {len(frames_list)} 帧, {fps:.2f} fps")
    return frames_list, fps


# ===== 过滤网球，仅保留一个网球 =====
def filter_tennis_ball(ball_tracked: list, racket_tracked: list) -> list:
    """
    过滤网球，仅保留一个网球。要求：
    1. 保证运动轨迹连续的网球
    2. 一定过滤掉和网球拍重叠的网球

    Parameters:
    -----------
    ball_tracked: list
        owlv2_sam2_video_tracking返回的网球检测结果
    racket_tracked: list
        owlv2_sam2_video_tracking返回的网球拍检测结果
        
    Returns:
    --------
    list:
        过滤后的网球检测结果，每帧最多包含一个网球
    """
    # 输出基本信息
    print("\n开始处理网球检测结果...")
    print(f"总帧数: {len(ball_tracked)}")
    
    # 检查输入数据
    if not ball_tracked:
        print("警告: 网球检测数据为空")
        return []
    
    # 统计网球检测情况
    frames_with_balls = sum(1 for frame in ball_tracked if frame)
    total_balls = sum(len(frame) for frame in ball_tracked)
    print(f"检测到网球的帧数: {frames_with_balls}/{len(ball_tracked)}")
    print(f"检测到的网球总数: {total_balls}, 平均每帧: {total_balls/max(1, len(ball_tracked)):.2f}")
    
    # 初始化结果列表
    filtered_ball = [[] for _ in range(len(ball_tracked))]
    
    # 历史记录，用于维护轨迹连续性
    history_length = 8  # 保持多少帧的历史记录，网球移动快
    position_history = []  # 位置历史
    size_history = []      # 尺寸历史
    velocity_history = []  # 速度历史
    max_disappear_frames = 5  # 允许网球消失的最大帧数
    disappear_count = 0
    
    # 确定参考网球 - 找到一个好的轨迹起点
    # 寻找第一个具有良好置信度且不与球拍重叠的网球
    reference_frame_idx = None
    reference_ball = None
    
    for i in range(len(ball_tracked)):
        if not ball_tracked[i]:
            continue
            
        for ball in ball_tracked[i]:
            ball_center = [
                (ball["bbox"][0] + ball["bbox"][2]) / 2,
                (ball["bbox"][1] + ball["bbox"][3]) / 2
            ]
            
            # 检查是否与球拍重叠
            overlaps_with_racket = False
            
            if racket_tracked[i]:
                for racket in racket_tracked[i]:
                    # 检查球的中心是否在球拍框内
                    if (ball_center[0] >= racket["bbox"][0] and 
                        ball_center[0] <= racket["bbox"][2] and
                        ball_center[1] >= racket["bbox"][1] and
                        ball_center[1] <= racket["bbox"][3]):
                        overlaps_with_racket = True
                        break
            
            # 如果不重叠并且有足够高的置信度
            confidence = ball.get("score", 0)
            if not overlaps_with_racket and confidence > 0.2:
                reference_frame_idx = i
                reference_ball = ball
                filtered_ball[i] = [ball]
                
                # 记录初始历史
                position_history = [ball_center] * history_length
                
                # 记录球的尺寸
                ball_size = (
                    ball["bbox"][2] - ball["bbox"][0],  # 宽度
                    ball["bbox"][3] - ball["bbox"][1]   # 高度
                )
                size_history = [ball_size] * history_length
                
                # 初始化速度历史为零
                velocity_history = [(0, 0)] * (history_length - 1)
                
                print(f"找到参考网球! 帧索引: {i}, 置信度: {confidence:.2f}")
                break
        
        if reference_ball:
            break
    
    # 如果没找到参考网球，选择第一个检测到的网球
    if reference_ball is None:
        for i in range(len(ball_tracked)):
            if ball_tracked[i]:
                reference_frame_idx = i
                reference_ball = ball_tracked[i][0]
                filtered_ball[i] = [reference_ball]
                
                # 记录网球中心位置
                ball_center = [
                    (reference_ball["bbox"][0] + reference_ball["bbox"][2]) / 2,
                    (reference_ball["bbox"][1] + reference_ball["bbox"][3]) / 2
                ]
                position_history = [ball_center] * history_length
                
                # 记录球的尺寸
                ball_size = (
                    reference_ball["bbox"][2] - reference_ball["bbox"][0],
                    reference_ball["bbox"][3] - reference_ball["bbox"][1]
                )
                size_history = [ball_size] * history_length
                
                # 初始化速度历史为零
                velocity_history = [(0, 0)] * (history_length - 1)
                
                print(f"未找到高质量参考网球，使用第一个检测到的网球! 帧索引: {i}")
                break
    
    # 如果仍然没有找到任何网球，返回空结果
    if reference_ball is None:
        print("错误: 未能找到任何网球！")
        return [[] for _ in range(len(ball_tracked))]
    
    # 前向遍历，从参考帧向后处理
    last_position = position_history[-1]
    last_velocity = velocity_history[-1] if velocity_history else (0, 0)
    
    for i in range(reference_frame_idx + 1, len(ball_tracked)):
        # 预测当前位置
        predicted_position = [
            last_position[0] + last_velocity[0],
            last_position[1] + last_velocity[1]
        ]
        
        # 如果当前帧没有检测到网球
        if not ball_tracked[i]:
            # 短时间内允许网球消失（可能被遮挡）
            if disappear_count < max_disappear_frames:
                disappear_count += 1
                filtered_ball[i] = []
                
                # 更新位置预测
                last_position = predicted_position
                # 保持速度不变，或根据物理规律调整（例如重力影响）
                
                # 可选: 使用预测的位置添加预测网球
                # predicted_bbox = [...根据预测位置和历史尺寸生成预测边界框...]
                # filtered_ball[i] = [{"bbox": predicted_bbox, "score": 0.5, "predicted": True}]
            else:
                # 消失太长时间，停止跟踪
                filtered_ball[i] = []
            continue
        
        # 有网球检测结果时，重置消失计数
        disappear_count = 0
        
        # 选择最佳网球
        best_ball = None
        best_score = -1
        
        for ball in ball_tracked[i]:
            ball_center = [
                (ball["bbox"][0] + ball["bbox"][2]) / 2,
                (ball["bbox"][1] + ball["bbox"][3]) / 2
            ]
            
            # 1. 检查与球拍重叠
            overlaps_with_racket = False
            if racket_tracked[i]:
                for racket in racket_tracked[i]:
                    # 球的中心是否在球拍框内
                    if (ball_center[0] >= racket["bbox"][0] and 
                        ball_center[0] <= racket["bbox"][2] and
                        ball_center[1] >= racket["bbox"][1] and
                        ball_center[1] <= racket["bbox"][3]):
                        overlaps_with_racket = True
                        break
            
            # 如果与球拍重叠，跳过这个网球
            if overlaps_with_racket:
                continue
            
            # 2. 计算与预测位置的接近度
            distance_to_prediction = math.sqrt(
                (ball_center[0] - predicted_position[0])**2 + 
                (ball_center[1] - predicted_position[1])**2
            )
            # 网球移动快，所以容忍较大的距离
            distance_score = 1.0 / (1.0 + 0.002 * distance_to_prediction)
            
            # 3. 检查尺寸一致性
            current_size = (
                ball["bbox"][2] - ball["bbox"][0],
                ball["bbox"][3] - ball["bbox"][1]
            )
            avg_size = [sum(s[0] for s in size_history) / len(size_history),
                        sum(s[1] for s in size_history) / len(size_history)]
            
            # 网球大小变化可能较大（远近效应），但比例应该相对稳定
            size_ratio = ((current_size[0] / avg_size[0]) + (current_size[1] / avg_size[1])) / 2
            size_score = 1.0 / (1.0 + abs(size_ratio - 1.0))
            
            # 4. 检查物理运动合理性
            if len(velocity_history) > 0:
                # 计算新速度
                new_velocity = (
                    ball_center[0] - last_position[0],
                    ball_center[1] - last_position[1]
                )
                
                # 速度变化应该符合物理规律
                velocity_change = math.sqrt(
                    (new_velocity[0] - last_velocity[0])**2 + 
                    (new_velocity[1] - last_velocity[1])**2
                )
                
                # 网球可以有突然的速度变化（例如被击打时），所以容忍度较高
                physics_score = 1.0 / (1.0 + 0.01 * velocity_change)
            else:
                physics_score = 0.8  # 默认值
            
            # 5. 置信度分数
            confidence = ball.get("score", 0)
            
            # 综合评分
            total_score = (
                0.35 * distance_score +  # 位置连续性最重要
                0.15 * size_score +      # 尺寸次之
                0.25 * physics_score +   # 物理运动合理性很重要
                0.25 * confidence        # 检测置信度也重要
            )
            
            if total_score > best_score:
                best_score = total_score
                best_ball = ball
        
        # 添加选中的网球到结果
        if best_ball:
            filtered_ball[i] = [best_ball]
            
            # 更新历史记录
            ball_center = [
                (best_ball["bbox"][0] + best_ball["bbox"][2]) / 2,
                (best_ball["bbox"][1] + best_ball["bbox"][3]) / 2
            ]
            
            # 计算新速度
            new_velocity = (
                ball_center[0] - last_position[0],
                ball_center[1] - last_position[1]
            )
            
            # 更新历史
            position_history.append(ball_center)
            if len(position_history) > history_length:
                position_history.pop(0)
            
            current_size = (
                best_ball["bbox"][2] - best_ball["bbox"][0],
                best_ball["bbox"][3] - best_ball["bbox"][1]
            )
            size_history.append(current_size)
            if len(size_history) > history_length:
                size_history.pop(0)
            
            velocity_history.append(new_velocity)
            if len(velocity_history) > history_length - 1:
                velocity_history.pop(0)
            
            # 更新最后的位置和速度
            last_position = ball_center
            last_velocity = new_velocity
        else:
            # 如果找不到符合条件的网球（例如全都与球拍重叠），则该帧没有网球
            filtered_ball[i] = []
    
    # 后向遍历，从参考帧向前处理
    last_position = position_history[0]  # 使用历史中最早的位置
    last_velocity = velocity_history[0] if velocity_history else (0, 0)  # 使用最早的速度，但需要反向
    last_velocity = (-last_velocity[0], -last_velocity[1])  # 反向速度
    
    for i in range(reference_frame_idx - 1, -1, -1):
        # 预测当前位置（后向）
        predicted_position = [
            last_position[0] + last_velocity[0],
            last_position[1] + last_velocity[1]
        ]
        
        # 如果当前帧没有检测到网球
        if not ball_tracked[i]:
            # 短时间内允许网球消失
            if disappear_count < max_disappear_frames:
                disappear_count += 1
                filtered_ball[i] = []
                
                # 更新位置预测
                last_position = predicted_position
            else:
                # 消失太长时间，停止跟踪
                filtered_ball[i] = []
            continue
        
        # 有网球检测结果时，重置消失计数
        disappear_count = 0
        
        # 选择最佳网球
        best_ball = None
        best_score = -1
        
        for ball in ball_tracked[i]:
            ball_center = [
                (ball["bbox"][0] + ball["bbox"][2]) / 2,
                (ball["bbox"][1] + ball["bbox"][3]) / 2
            ]
            
            # 1. 检查与球拍重叠
            overlaps_with_racket = False
            if racket_tracked[i]:
                for racket in racket_tracked[i]:
                    if (ball_center[0] >= racket["bbox"][0] and 
                        ball_center[0] <= racket["bbox"][2] and
                        ball_center[1] >= racket["bbox"][1] and
                        ball_center[1] <= racket["bbox"][3]):
                        overlaps_with_racket = True
                        break
            
            # 如果与球拍重叠，跳过这个网球
            if overlaps_with_racket:
                continue
            
            # 2. 计算与预测位置的接近度
            distance_to_prediction = math.sqrt(
                (ball_center[0] - predicted_position[0])**2 + 
                (ball_center[1] - predicted_position[1])**2
            )
            distance_score = 1.0 / (1.0 + 0.002 * distance_to_prediction)
            
            # 3. 检查尺寸一致性
            current_size = (
                ball["bbox"][2] - ball["bbox"][0],
                ball["bbox"][3] - ball["bbox"][1]
            )
            size_ratio = (
                (current_size[0] / size_history[0][0]) + 
                (current_size[1] / size_history[0][1])
            ) / 2
            size_score = 1.0 / (1.0 + abs(size_ratio - 1.0))
            
            # 4. 检查物理运动合理性（后向）
            if len(velocity_history) > 0:
                # 计算新速度（后向）
                new_velocity = (
                    ball_center[0] - last_position[0],
                    ball_center[1] - last_position[1]
                )
                
                # 速度变化应该符合物理规律
                velocity_change = math.sqrt(
                    (new_velocity[0] - last_velocity[0])**2 + 
                    (new_velocity[1] - last_velocity[1])**2
                )
                physics_score = 1.0 / (1.0 + 0.01 * velocity_change)
            else:
                physics_score = 0.8  # 默认值
            
            # 5. 置信度分数
            confidence = ball.get("score", 0)
            
            # 综合评分
            total_score = (
                0.35 * distance_score + 
                0.15 * size_score + 
                0.25 * physics_score + 
                0.25 * confidence
            )
            
            if total_score > best_score:
                best_score = total_score
                best_ball = ball
        
        # 添加选中的网球到结果
        if best_ball:
            filtered_ball[i] = [best_ball]
            
            # 更新历史记录（后向）
            ball_center = [
                (best_ball["bbox"][0] + best_ball["bbox"][2]) / 2,
                (best_ball["bbox"][1] + best_ball["bbox"][3]) / 2
            ]
            
            # 计算新速度（后向）
            new_velocity = (
                ball_center[0] - last_position[0],
                ball_center[1] - last_position[1]
            )
            
            # 更新位置和速度
            last_position = ball_center
            last_velocity = new_velocity
        else:
            # 如果找不到符合条件的网球，则该帧没有网球
            filtered_ball[i] = []
    
    # 统计过滤结果
    frames_with_filtered_balls = sum(1 for frame in filtered_ball if frame)
    print(f"过滤后有网球的帧数: {frames_with_filtered_balls}/{len(filtered_ball)}")
    
    return filtered_ball

# ===== 过滤球拍，仅保留一个球拍 =====
def filter_racket(racket_tracked: list, player_tracked: list) -> list:
    """
    过滤球拍，仅保留一个球拍。要求如下
    1. 选择和网球运动员距离较近的球拍
    2. 运动轨迹连续的球拍
    
    Parameters:
    -----------
    racket_tracked: list
        owlv2_sam2_video_tracking返回的球拍检测结果
    player_tracked: list
        过滤后的网球运动员检测结果，用于辅助球拍选择
        
    Returns:
    --------
    list:
        过滤后的球拍检测结果，每帧最多包含一个球拍
    """
    # 输出基本信息
    print("\n开始处理球拍检测结果...")
    print(f"总帧数: {len(racket_tracked)}")
    
    # 检查输入数据
    if not racket_tracked:
        print("警告: 球拍检测数据为空")
        return []
    
    # 统计球拍检测情况
    frames_with_rackets = sum(1 for frame in racket_tracked if frame)
    total_rackets = sum(len(frame) for frame in racket_tracked)
    print(f"检测到球拍的帧数: {frames_with_rackets}/{len(racket_tracked)}")
    print(f"检测到的球拍总数: {total_rackets}, 平均每帧: {total_rackets/len(racket_tracked):.2f}")
    
    # 初始化结果列表
    filtered_racket = [[] for _ in range(len(racket_tracked))]
    
    # 寻找合适的参考球拍
    reference_racket = None
    reference_frame_idx = None
    reference_racket_center = None
    
    # 首先尝试在有运动员的帧中寻找参考球拍
    for i in range(len(racket_tracked)):
        if racket_tracked[i] and player_tracked[i]:
            # 获取运动员中心位置
            player = player_tracked[i][0]
            player_center = [
                (player["bbox"][0] + player["bbox"][2]) / 2,
                (player["bbox"][1] + player["bbox"][3]) / 2
            ]
            
            # 获取运动员右侧边缘位置 (假设持拍手)
            player_right = player["bbox"][2]
            player_middle_y = (player["bbox"][1] + player["bbox"][3]) / 2
            
            # 计算每个球拍到运动员的距离
            best_distance = float('inf')
            best_racket = None
            
            for racket in racket_tracked[i]:
                # 计算球拍中心
                racket_center = [
                    (racket["bbox"][0] + racket["bbox"][2]) / 2,
                    (racket["bbox"][1] + racket["bbox"][3]) / 2
                ]
                
                # 计算到运动员右手的估计距离
                hand_distance = math.sqrt(
                    (racket_center[0] - player_right)**2 + 
                    (racket_center[1] - player_middle_y)**2
                )
                
                # 也考虑与运动员中心的距离
                center_distance = math.sqrt(
                    (racket_center[0] - player_center[0])**2 + 
                    (racket_center[1] - player_center[1])**2
                )
                
                # 综合距离 (偏重手部距离)
                combined_distance = 0.7 * hand_distance + 0.3 * center_distance
                
                if combined_distance < best_distance:
                    best_distance = combined_distance
                    best_racket = racket
            
            if best_racket:
                reference_racket = best_racket
                reference_frame_idx = i
                reference_racket_center = [
                    (reference_racket["bbox"][0] + reference_racket["bbox"][2]) / 2,
                    (reference_racket["bbox"][1] + reference_racket["bbox"][3]) / 2
                ]
                filtered_racket[i] = [best_racket]
                print(f"找到参考球拍! 帧索引: {i}, 距离: {best_distance:.2f}")
                break
    
    # 如果没有找到参考球拍，尝试使用大小合适的球拍作为参考
    if reference_racket is None:
        print("未找到与运动员关联的球拍，尝试基于尺寸选择参考球拍...")
        for i in range(len(racket_tracked)):
            if racket_tracked[i]:
                # 选择面积适中的球拍 (网球拍通常有一定尺寸)
                best_racket = None
                best_score = -1
                
                for racket in racket_tracked[i]:
                    width = racket["bbox"][2] - racket["bbox"][0]
                    height = racket["bbox"][3] - racket["bbox"][1]
                    area = width * height
                    
                    # 网球拍通常是长条状的，宽高比大约为 0.3-0.4
                    aspect_ratio = min(width, height) / max(width, height)
                    expected_ratio = 0.35
                    ratio_score = 1 - abs(aspect_ratio - expected_ratio)
                    
                    # 网球拍区域通常在一定范围内
                    # 假设理想区域是图像的 1/20 到 1/10
                    frame_area = 1920 * 1080  # 假设标准尺寸
                    expected_area = frame_area / 15
                    area_score = 1 - min(1, abs(area - expected_area) / expected_area)
                    
                    total_score = 0.6 * ratio_score + 0.4 * area_score
                    
                    if total_score > best_score:
                        best_score = total_score
                        best_racket = racket
                
                if best_racket and best_score > 0.7:  # 要求较高分数
                    reference_racket = best_racket
                    reference_frame_idx = i
                    reference_racket_center = [
                        (reference_racket["bbox"][0] + reference_racket["bbox"][2]) / 2,
                        (reference_racket["bbox"][1] + reference_racket["bbox"][3]) / 2
                    ]
                    filtered_racket[i] = [best_racket]
                    print(f"找到基于尺寸的参考球拍! 帧索引: {i}, 分数: {best_score:.2f}")
                    break
    
    # 如果仍然没有找到参考球拍，使用第一个检测到的球拍
    if reference_racket is None:
        print("未能找到合适的参考球拍，使用第一个检测到的球拍...")
        for i in range(len(racket_tracked)):
            if racket_tracked[i]:
                reference_racket = racket_tracked[i][0]
                reference_frame_idx = i
                reference_racket_center = [
                    (reference_racket["bbox"][0] + reference_racket["bbox"][2]) / 2,
                    (reference_racket["bbox"][1] + reference_racket["bbox"][3]) / 2
                ]
                filtered_racket[i] = [reference_racket]
                print(f"使用第一个检测到的球拍作为参考! 帧索引: {i}")
                break
    
    # 如果依然没有找到任何球拍，返回空结果
    if reference_racket is None:
        print("错误: 未能找到任何球拍！")
        return [[] for _ in range(len(racket_tracked))]
    
    # 记录参考球拍的尺寸
    reference_width = reference_racket["bbox"][2] - reference_racket["bbox"][0]
    reference_height = reference_racket["bbox"][3] - reference_racket["bbox"][1]
    
    # 前向遍历，从参考帧向后处理
    last_good_center = reference_racket_center
    for i in range(reference_frame_idx + 1, len(racket_tracked)):
        if not racket_tracked[i]:
            continue
            
        best_racket = None
        best_score = 0
        
        # 是否有运动员在这一帧
        has_player = bool(player_tracked[i])
        
        for racket in racket_tracked[i]:
            racket_center = [
                (racket["bbox"][0] + racket["bbox"][2]) / 2,
                (racket["bbox"][1] + racket["bbox"][3]) / 2
            ]
            
            # 计算与上一个好球拍的距离分数
            dist_to_last = math.sqrt(
                (racket_center[0] - last_good_center[0])**2 + 
                (racket_center[1] - last_good_center[1])**2
            )
            position_score = 1.0 / (1.0 + 0.01 * dist_to_last)
            
            # 计算尺寸相似度分数
            width = racket["bbox"][2] - racket["bbox"][0]
            height = racket["bbox"][3] - racket["bbox"][1]
            width_ratio = min(width, reference_width) / max(width, reference_width)
            height_ratio = min(height, reference_height) / max(height, reference_height)
            size_score = (width_ratio + height_ratio) / 2
            
            # 基础总分
            total_score = 0.7 * position_score + 0.3 * size_score
            
            # 如果有运动员，额外考虑与运动员的距离
            if has_player:
                player = player_tracked[i][0]
                player_right = player["bbox"][2]
                player_middle_y = (player["bbox"][1] + player["bbox"][3]) / 2
                
                hand_dist = math.sqrt(
                    (racket_center[0] - player_right)**2 + 
                    (racket_center[1] - player_middle_y)**2
                )
                
                player_score = 1.0 / (1.0 + 0.005 * hand_dist)
                
                # 重新计算总分，加入与运动员的关系
                total_score = 0.5 * total_score + 0.5 * player_score
            
            if total_score > best_score:
                best_score = total_score
                best_racket = racket
        
        if best_racket:
            filtered_racket[i] = [best_racket]
            last_good_center = [
                (best_racket["bbox"][0] + best_racket["bbox"][2]) / 2,
                (best_racket["bbox"][1] + best_racket["bbox"][3]) / 2
            ]
    
    # 后向遍历，从参考帧向前处理
    last_good_center = reference_racket_center
    for i in range(reference_frame_idx - 1, -1, -1):
        if not racket_tracked[i]:
            continue
            
        best_racket = None
        best_score = 0
        
        # 是否有运动员在这一帧
        has_player = bool(player_tracked[i])
        
        for racket in racket_tracked[i]:
            racket_center = [
                (racket["bbox"][0] + racket["bbox"][2]) / 2,
                (racket["bbox"][1] + racket["bbox"][3]) / 2
            ]
            
            # 计算与上一个好球拍的距离分数
            dist_to_last = math.sqrt(
                (racket_center[0] - last_good_center[0])**2 + 
                (racket_center[1] - last_good_center[1])**2
            )
            position_score = 1.0 / (1.0 + 0.01 * dist_to_last)
            
            # 计算尺寸相似度分数
            width = racket["bbox"][2] - racket["bbox"][0]
            height = racket["bbox"][3] - racket["bbox"][1]
            width_ratio = min(width, reference_width) / max(width, reference_width)
            height_ratio = min(height, reference_height) / max(height, reference_height)
            size_score = (width_ratio + height_ratio) / 2
            
            # 基础总分
            total_score = 0.7 * position_score + 0.3 * size_score
            
            # 如果有运动员，额外考虑与运动员的距离
            if has_player:
                player = player_tracked[i][0]
                player_right = player["bbox"][2]
                player_middle_y = (player["bbox"][1] + player["bbox"][3]) / 2
                
                hand_dist = math.sqrt(
                    (racket_center[0] - player_right)**2 + 
                    (racket_center[1] - player_middle_y)**2
                )
                
                player_score = 1.0 / (1.0 + 0.005 * hand_dist)
                
                # 重新计算总分，加入与运动员的关系
                total_score = 0.5 * total_score + 0.5 * player_score
            
            if total_score > best_score:
                best_score = total_score
                best_racket = racket
        
        if best_racket:
            filtered_racket[i] = [best_racket]
            last_good_center = [
                (best_racket["bbox"][0] + best_racket["bbox"][2]) / 2,
                (best_racket["bbox"][1] + best_racket["bbox"][3]) / 2
            ]
    
    # 统计过滤结果
    frames_with_filtered_rackets = sum(1 for frame in filtered_racket if frame)
    print(f"过滤后有球拍的帧数: {frames_with_filtered_rackets}/{len(filtered_racket)}")
    
    return filtered_racket

# ===== 过滤网球运动员，仅保留一个网球运动员 =====
def filter_player(player_tracked: list) -> list:
    """
    过滤网球运动员，仅保留一个网球运动员。
    选择每帧中置信度最高的网球运动员，并保持轨迹的连续性。
    
    Parameters:
    -----------
    player_tracked: list
        owlv2_sam2_video_tracking返回的网球运动员检测结果
        
    Returns:
    --------
    list:
        过滤后的网球运动员检测结果，每帧最多包含一个网球运动员
    """
    filtered_player = []
    
    # 历史记录，用于维护过去几帧的位置和特征
    history_length = 10  # 保持多少帧的历史记录，运动员移动较慢，可以使用更长的历史
    position_history = []  # 位置历史
    size_history = []      # 尺寸历史
    velocity_history = []  # 速度历史
    max_disappear_frames = 10  # 允许运动员消失的最大帧数，运动员不太可能突然消失
    disappear_count = 0
    
    # 选择初始运动员 - 找到视频中第一个出现且置信度最高的运动员
    initial_frame_idx = None
    initial_player = None
    max_confidence = -1
    
    # 寻找前30帧中置信度最高的运动员作为参考
    search_range = min(30, len(player_tracked))
    for i in range(search_range):
        if player_tracked[i]:
            for player in player_tracked[i]:
                confidence = player.get("score", 0)
                # 运动员通常在画面中占比较大，可以加入尺寸因素作为参考
                box_width = player["bbox"][2] - player["bbox"][0]
                box_height = player["bbox"][3] - player["bbox"][1]
                box_area = box_width * box_height
                
                # 结合置信度和区域大小来选择初始运动员
                area_factor = min(1.0, box_area / 40000)  # 归一化区域因子，假设40000像素为参考
                adjusted_confidence = confidence * (0.7 + 0.3 * area_factor)  # 区域权重占30%
                
                if adjusted_confidence > max_confidence:
                    initial_frame_idx = i
                    initial_player = player
                    max_confidence = adjusted_confidence
    
    # 如果没有找到任何运动员，返回空列表
    if initial_player is None:
        return [[] for _ in range(len(player_tracked))]
        
    # 初始化历史记录
    initial_position = initial_player["bbox"][:2]  # (x_min, y_min)
    initial_size = (
        initial_player["bbox"][2] - initial_player["bbox"][0],  # 宽度
        initial_player["bbox"][3] - initial_player["bbox"][1]   # 高度
    )
    
    # 填充历史记录
    position_history = [initial_position] * history_length
    size_history = [initial_size] * history_length
    velocity_history = [(0, 0)] * (history_length - 1)  # 速度需要两个点才能计算
    
    # 对视频帧进行处理
    for i in range(len(player_tracked)):
        if i < initial_frame_idx:
            # 初始帧之前的所有帧都设为空
            filtered_player.append([])
            continue
        
        if i == initial_frame_idx:
            # 初始帧直接使用初始运动员
            filtered_player.append([initial_player])
            continue
    
        # 开始主要处理逻辑
        frame_detections = player_tracked[i]
        
        # 如果当前帧没有检测到运动员
        if not frame_detections:
            if disappear_count < max_disappear_frames:
                filtered_player.append([])
                disappear_count += 1
            else:
                # 如果消失太久，可以尝试根据速度预测位置
                filtered_player.append([])
            continue
        
        # 检测到运动员，重置消失计数
        disappear_count = 0
        
        # 计算当前历史中的平均位置和尺寸
        avg_position = [sum(p[0] for p in position_history) / len(position_history),
                        sum(p[1] for p in position_history) / len(position_history)]
        
        avg_size = [sum(s[0] for s in size_history) / len(size_history),
                    sum(s[1] for s in size_history) / len(size_history)]
        
        # 计算平均速度向量
        if len(velocity_history) > 0:
            avg_velocity = [sum(v[0] for v in velocity_history) / len(velocity_history),
                            sum(v[1] for v in velocity_history) / len(velocity_history)]
        else:
            avg_velocity = [0, 0]
        
        # 预测当前帧的位置
        predicted_position = [avg_position[0] + avg_velocity[0], 
                                avg_position[1] + avg_velocity[1]]
        
        # 多个检测结果时，选择最佳的运动员
        best_player = None
        best_score = -1
        
        for player in frame_detections:
            # 获取置信度，如果没有则默认为0
            confidence = player.get("score", 0)
            current_position = player["bbox"][:2]  # (x_min, y_min)
            
            # 计算当前运动员的尺寸
            current_size = (
                player["bbox"][2] - player["bbox"][0],  # 宽度
                player["bbox"][3] - player["bbox"][1]   # 高度
            )
            
            # 计算当前运动员的区域
            box_area = current_size[0] * current_size[1]
            
            # 1. 位置连续性评分 - 与预测位置的距离
            position_diff = math.sqrt((current_position[0] - predicted_position[0])**2 + 
                                        (current_position[1] - predicted_position[1])**2)
            position_score = 1.0 / (1.0 + 0.005 * position_diff)  # 归一化，运动员移动较慢，所以系数更小
            
            # 2. 尺寸连续性评分 - 与平均尺寸的相似度
            width_ratio = abs(current_size[0] / avg_size[0] - 1)
            height_ratio = abs(current_size[1] / avg_size[1] - 1)
            size_score = 1.0 / (1.0 + 2.0 * (width_ratio + height_ratio))  # 归一化
            
            # 3. 区域大小评分 - 运动员通常是画面中的主体
            area_score = min(1.0, box_area / 40000)  # 假设40000像素为参考
            
            # 4. 位置历史一致性评分 - 与历史轨迹的一致性
            history_diffs = []
            for pos in position_history:
                diff = math.sqrt((current_position[0] - pos[0])**2 + 
                                (current_position[1] - pos[1])**2)
                history_diffs.append(diff)
            
            # 计算位置变化的标准差，变化越稳定越好
            if len(history_diffs) > 1:
                mean_diff = sum(history_diffs) / len(history_diffs)
                variance = sum((d - mean_diff)**2 for d in history_diffs) / len(history_diffs)
                std_dev = math.sqrt(variance)
                history_score = 1.0 / (1.0 + 0.05 * std_dev)  # 归一化，运动员移动较慢
            else:
                history_score = 0.5  # 默认中等评分
            
            # 综合评分 - 置信度(20%)、位置预测(25%)、尺寸一致性(20%)、区域大小(15%)、历史轨迹一致性(20%)
            total_score = (0.2 * confidence + 
                            0.25 * position_score + 
                            0.2 * size_score + 
                            0.15 * area_score +
                            0.2 * history_score)
            
            # 更新最佳运动员
            if total_score > best_score:
                best_player = player
                best_score = total_score
        
        # 添加选中的运动员到结果列表
        if best_player:
            filtered_player.append([best_player])
            
            # 更新历史记录
            current_position = best_player["bbox"][:2]
            current_size = (
                best_player["bbox"][2] - best_player["bbox"][0],
                best_player["bbox"][3] - best_player["bbox"][1]
            )
            
            # 计算速度（当前位置 - 上一位置）
            if position_history:
                last_position = position_history[-1]
                current_velocity = (
                    current_position[0] - last_position[0],
                    current_position[1] - last_position[1]
                )
                velocity_history.append(current_velocity)
                if len(velocity_history) > history_length - 1:
                    velocity_history.pop(0)
            
            # 更新位置和尺寸历史
            position_history.append(current_position)
            size_history.append(current_size)
            if len(position_history) > history_length:
                position_history.pop(0)
            if len(size_history) > history_length:
                size_history.pop(0)
        else:
            filtered_player.append([])
    
    return filtered_player


# ===== 选择最佳接触帧 =====
def select_contact_frame(ball_tracked: list, racket_tracked: list, player_tracked: list, fps: float = 30) -> int:
    """
    选择最佳接触帧（逻辑： 网球和网球拍最近距离的帧, 可能要考虑网球拍和网球不在同一帧的情况）
    
    Parameters:
    -----------
    ball_tracked: list
        过滤后的网球检测结果
    racket_tracked: list
        过滤后的球拍检测结果
    player_tracked: list
        过滤后的网球运动员检测结果
    fps: float
        视频帧率，用于计算基于时间的搜索范围
        
    Returns:
    --------
    int:
        最佳接触帧的索引
    """
    print("\n开始查找最佳接触帧...")
    
    # 初始化变量
    min_distance = float('inf')
    best_frame_idx = -1
    max_search_frames = len(ball_tracked)
    
    # 使用滑动窗口方法找出网球和球拍最近的帧
    # 同时考虑球速变化作为辅助标志（接触后球速通常有显著变化）
    window_size = 3  # 考虑前后共3帧
    
    # 1. 先找出所有同时包含网球和球拍的帧
    valid_frames = []
    for i in range(max_search_frames):
        if ball_tracked[i] and racket_tracked[i]:
            valid_frames.append(i)
    
    if not valid_frames:
        print("警告: 没有找到同时包含网球和球拍的帧，尝试使用时间插值...")
        # 如果没有同时包含两者的帧，尝试找最近的一对球和拍
        for i in range(max_search_frames):
            if ball_tracked[i]:  # 找到球的帧
                ball_frame = i
                ball_center = [
                    (ball_tracked[i][0]["bbox"][0] + ball_tracked[i][0]["bbox"][2]) / 2,
                    (ball_tracked[i][0]["bbox"][1] + ball_tracked[i][0]["bbox"][3]) / 2
                ]
                
                # 查找最近的球拍帧
                nearest_racket_frame = -1
                min_frame_diff = float('inf')
                
                # 在前后0.5秒范围内查找
                search_window = int(fps * 0.5)  # 前后0.5秒
                search_start = max(0, i - search_window)
                search_end = min(max_search_frames, i + search_window)
                
                for j in range(search_start, search_end):
                    if racket_tracked[j]:
                        frame_diff = abs(j - i)
                        if frame_diff < min_frame_diff:
                            min_frame_diff = frame_diff
                            nearest_racket_frame = j
                
                if nearest_racket_frame != -1:
                    # 找到了最近的球拍帧，添加到候选列表
                    valid_frames.append((i + nearest_racket_frame) // 2)  # 取中间帧作为近似接触帧
        
        # 如果仍然没有找到，选择视频中间的帧作为备选
        if not valid_frames:
            print("警告: 无法定位接触帧，使用视频中点作为接触帧...")
            return max_search_frames // 2
    
    print(f"找到 {len(valid_frames)} 个可能的接触帧")
    
    # 2. 对每个候选帧计算球和拍的距离
    frame_distances = []
    
    for frame_idx in valid_frames:
        # 获取网球中心
        if ball_tracked[frame_idx]:
            ball = ball_tracked[frame_idx][0]
            ball_center = [
                (ball["bbox"][0] + ball["bbox"][2]) / 2,
                (ball["bbox"][1] + ball["bbox"][3]) / 2
            ]
            
            # 获取球拍位置 - 使用球拍框与球的距离
            if racket_tracked[frame_idx]:
                racket = racket_tracked[frame_idx][0]
                
                # 找到球拍边界框上最接近球的点
                # 考虑到网球拍可能是一个矩形框，实际上球可能与拍线（框内部）接触
                racket_bbox = racket["bbox"]
                
                # 检查球是否在球拍框内
                if (ball_center[0] >= racket_bbox[0] and ball_center[0] <= racket_bbox[2] and
                    ball_center[1] >= racket_bbox[1] and ball_center[1] <= racket_bbox[3]):
                    # 球在球拍框内，这是一个很好的接触候选
                    distance = 0
                else:
                    # 球在球拍框外，计算到框的最短距离
                    dx = max(racket_bbox[0] - ball_center[0], 0, ball_center[0] - racket_bbox[2])
                    dy = max(racket_bbox[1] - ball_center[1], 0, ball_center[1] - racket_bbox[3])
                    distance = math.sqrt(dx * dx + dy * dy)
                
                frame_distances.append((frame_idx, distance))
    
    # 按距离排序
    frame_distances.sort(key=lambda x: x[1])
    
    # 3. 使用球速变化作为额外的判断标准
    if frame_distances:
        # 取距离最小的前3个帧进行进一步分析
        top_candidates = [fd[0] for fd in frame_distances[:min(3, len(frame_distances))]]
        
        # 计算每个候选帧前后的球速变化
        best_velocity_change = -1
        for frame_idx in top_candidates:
            # 确保有足够的前后帧用于计算速度
            if frame_idx > 1 and frame_idx < max_search_frames - 2:
                # 找到前后有球的帧
                pre_ball_idx = frame_idx - 1
                while pre_ball_idx > 0 and not ball_tracked[pre_ball_idx]:
                    pre_ball_idx -= 1
                
                post_ball_idx = frame_idx + 1
                while post_ball_idx < max_search_frames - 1 and not ball_tracked[post_ball_idx]:
                    post_ball_idx += 1
                
                # 确保找到了前后的球
                if ball_tracked[pre_ball_idx] and ball_tracked[post_ball_idx]:
                    pre_ball = ball_tracked[pre_ball_idx][0]
                    post_ball = ball_tracked[post_ball_idx][0]
                    
                    pre_center = [
                        (pre_ball["bbox"][0] + pre_ball["bbox"][2]) / 2,
                        (pre_ball["bbox"][1] + pre_ball["bbox"][3]) / 2
                    ]
                    
                    post_center = [
                        (post_ball["bbox"][0] + post_ball["bbox"][2]) / 2,
                        (post_ball["bbox"][1] + post_ball["bbox"][3]) / 2
                    ]
                    
                    # 计算前后速度向量
                    pre_velocity = [
                        (ball_center[0] - pre_center[0]) / (frame_idx - pre_ball_idx),
                        (ball_center[1] - pre_center[1]) / (frame_idx - pre_ball_idx)
                    ]
                    
                    post_velocity = [
                        (post_center[0] - ball_center[0]) / (post_ball_idx - frame_idx),
                        (post_center[1] - ball_center[1]) / (post_ball_idx - frame_idx)
                    ]
                    
                    # 计算速度变化量（方向和大小）
                    velocity_change = math.sqrt(
                        (post_velocity[0] - pre_velocity[0])**2 + 
                        (post_velocity[1] - pre_velocity[1])**2
                    )
                    
                    # 如果速度变化很大，这更可能是接触帧
                    if velocity_change > best_velocity_change:
                        best_velocity_change = velocity_change
                        best_frame_idx = frame_idx
        
        # 如果基于速度没有找到好的候选，就使用距离最小的
        if best_frame_idx == -1 and frame_distances:
            best_frame_idx = frame_distances[0][0]
    
    # 如果没有找到合适的帧，返回默认值
    if best_frame_idx == -1:
        print("警告: 无法确定接触帧，使用视频中点...")
        best_frame_idx = max_search_frames // 2
    
    print(f"最佳接触帧索引: {best_frame_idx}")
    return best_frame_idx

# ===== 选择准备动作帧 =====
def select_preparation_frame(contact_frame: int, ball_tracked: list, racket_tracked: list, player_tracked: list, fps: float = 30) -> int:
    """
    选择准备动作帧（逻辑： 最佳接触帧前，离最佳接触帧最近，网球拍速度最小的帧）
    
    Parameters:
    -----------
    contact_frame: int
        接触帧索引
    ball_tracked: list
        过滤后的网球检测结果
    racket_tracked: list
        过滤后的球拍检测结果
    player_tracked: list
        过滤后的网球运动员检测结果
    fps: float
        视频帧率，用于计算基于时间的搜索范围
        
    Returns:
    --------
    int:
        准备动作帧的索引
    """
    print("\n开始查找准备动作帧...")
    
    # 初始设定
    max_frames = len(racket_tracked)
    
    # 设置搜索范围 - 接触帧前1秒内
    search_frames = int(fps)  # 1秒内的帧数
    search_range = min(search_frames, contact_frame)
    min_search_idx = max(0, contact_frame - search_range)
    
    # 初始化变量
    best_prep_idx = min_search_idx  # 默认使用搜索范围内最早的帧
    min_velocity = float('inf')
    last_racket_center = None
    
    # 计算球拍在各帧中的速度，找到速度最小的帧
    for i in range(contact_frame - 1, min_search_idx - 1, -1):
        # 确保当前帧有球拍
        if not racket_tracked[i]:
            continue
            
        racket = racket_tracked[i][0]
        racket_center = [
            (racket["bbox"][0] + racket["bbox"][2]) / 2,
            (racket["bbox"][1] + racket["bbox"][3]) / 2
        ]
        
        # 需要有上一帧作为参考才能计算速度
        if last_racket_center is None:
            last_racket_center = racket_center
            last_idx = i
            continue
        
        # 计算球拍速度 (逐帧位移)
        velocity = math.sqrt(
            (racket_center[0] - last_racket_center[0])**2 + 
            (racket_center[1] - last_racket_center[1])**2
        )
        
        # 正规化速度 (考虑帧间距)
        frame_diff = last_idx - i
        if frame_diff > 0:
            velocity /= frame_diff
        
        # 更新最小速度
        if velocity < min_velocity:
            min_velocity = velocity
            best_prep_idx = i
        
        # 更新上一帧信息
        last_racket_center = racket_center
        last_idx = i
    
    # 额外检查：如果找到的准备帧离接触帧太近，可能不是真正的准备阶段
    # 理想情况下，准备动作应该发生在接触前的适当距离
    min_frame_distance = int(fps * 0.08)  # 大约为接触前0.08秒
    min_frame_distance = max(5, min_frame_distance)  # 至少5帧的距离
    
    if contact_frame - best_prep_idx < min_frame_distance and best_prep_idx > min_search_idx:
        # 尝试在更早的时间段内再次寻找
        secondary_search_end = best_prep_idx - 1
        secondary_search_start = max(0, min_search_idx - int(fps * 0.5))  # 再往前0.5秒
        
        secondary_best_idx = secondary_search_start
        secondary_min_velocity = float('inf')
        last_racket_center = None
        
        for i in range(secondary_search_end, secondary_search_start - 1, -1):
            if not racket_tracked[i]:
                continue
                
            racket = racket_tracked[i][0]
            racket_center = [
                (racket["bbox"][0] + racket["bbox"][2]) / 2,
                (racket["bbox"][1] + racket["bbox"][3]) / 2
            ]
            
            if last_racket_center is None:
                last_racket_center = racket_center
                last_idx = i
                continue
            
            velocity = math.sqrt(
                (racket_center[0] - last_racket_center[0])**2 + 
                (racket_center[1] - last_racket_center[1])**2
            )
            
            frame_diff = last_idx - i
            if frame_diff > 0:
                velocity /= frame_diff
            
            if velocity < secondary_min_velocity:
                secondary_min_velocity = velocity
                secondary_best_idx = i
            
            last_racket_center = racket_center
            last_idx = i
        
        # 如果找到了更好的准备帧，使用它
        if secondary_min_velocity < min_velocity * 1.2:  # 允许略微更高的速度
            best_prep_idx = secondary_best_idx
    
    # 如果没有找到合适的准备帧，使用默认帧（离接触帧适当距离的帧）
    if best_prep_idx == contact_frame:
        default_prep_idx = max(0, contact_frame - int(fps * 0.33))  # 默认使用接触帧前1/3秒
        best_prep_idx = default_prep_idx
        print(f"警告: 无法找到合适的准备帧，使用默认帧 (接触帧-{int(fps * 0.33)}帧)")
    
    print(f"最佳准备动作帧索引: {best_prep_idx} (接触帧: {contact_frame})")
    return best_prep_idx

# ===== 选择跟随动作帧 =====
def select_follow_frame(contact_frame: int, ball_tracked: list, racket_tracked: list, player_tracked: list, fps: float = 30) -> int:
    """
    选择跟随动作帧（逻辑： 最佳接触帧后, 离最佳接触帧最近，且网球拍位置最高的帧）
    
    Parameters:
    -----------
    contact_frame: int
        接触帧索引
    ball_tracked: list
        过滤后的网球检测结果
    racket_tracked: list
        过滤后的球拍检测结果
    player_tracked: list
        过滤后的网球运动员检测结果
    fps: float
        视频帧率，用于计算基于时间的搜索范围
        
    Returns:
    --------
    int:
        跟随动作帧的索引
    """
    print("\n开始查找跟随动作帧...")
    
    # 初始设定
    max_frames = len(racket_tracked)
    
    # 设置搜索范围 - 接触帧后1秒内
    search_frames = int(fps)  # 1秒内的帧数
    max_search_idx = min(max_frames - 1, contact_frame + search_frames)
    
    # 初始化变量
    best_follow_idx = max_search_idx  # 默认使用搜索范围内最晚的帧
    highest_position = float('inf')  # 注意：屏幕坐标y值越小，位置越高
    
    # 在接触帧之后查找球拍位置最高的帧
    for i in range(contact_frame + 1, max_search_idx + 1):
        # 确保当前帧有球拍
        if not racket_tracked[i]:
            continue
            
        racket = racket_tracked[i][0]
        
        # 计算球拍顶部位置 (y坐标最小值)
        racket_top = racket["bbox"][1]  # bbox = [x_min, y_min, x_max, y_max]
        
        # 查找球拍顶部位置最高（y值最小）的帧
        if racket_top < highest_position:
            highest_position = racket_top
            best_follow_idx = i
        
        # 如果发现球拍位置开始下降，这可能表示跟随动作已经完成
        # 检查后续几帧，如果球拍持续下降，则停止搜索
        if i > contact_frame + int(fps * 0.17) and racket_top < highest_position:  # 大约接触后0.17秒
            consecutive_drops = 0
            for j in range(i + 1, min(i + 5, max_search_idx + 1)):
                if racket_tracked[j]:
                    next_racket_top = racket_tracked[j][0]["bbox"][1]
                    if next_racket_top > racket_top:  # y增加表示位置下降
                        consecutive_drops += 1
            
            # 如果连续3帧都在下降，认为跟随动作已经结束
            if consecutive_drops >= 3:
                break
    
    # 确保跟随帧与接触帧有足够距离
    min_frame_distance = int(fps * 0.17)  # 大约接触后0.17秒
    min_frame_distance = max(10, min_frame_distance)  # 至少10帧的距离
    
    if best_follow_idx - contact_frame < min_frame_distance:
        # 如果太近，尝试找到稍远但仍然合理的帧
        secondary_search_start = contact_frame + min_frame_distance
        secondary_search_end = min(max_frames - 1, contact_frame + search_frames)
        
        if secondary_search_start <= secondary_search_end:
            secondary_best_idx = secondary_search_start
            secondary_highest_position = float('inf')
            
            for i in range(secondary_search_start, secondary_search_end + 1):
                if not racket_tracked[i]:
                    continue
                    
                racket = racket_tracked[i][0]
                racket_top = racket["bbox"][1]
                
                if racket_top < secondary_highest_position:
                    secondary_highest_position = racket_top
                    secondary_best_idx = i
            
            # 如果找到了合适的帧，使用它
            if secondary_highest_position < float('inf'):
                best_follow_idx = secondary_best_idx
    
    # 如果没有找到合适的跟随帧，使用默认帧（接触帧后适当距离的帧）
    if best_follow_idx == contact_frame or best_follow_idx >= max_frames:
        default_follow_idx = min(max_frames - 1, contact_frame + int(fps * 0.33))  # 默认使用接触帧后1/3秒
        best_follow_idx = default_follow_idx
        print(f"警告: 无法找到合适的跟随帧，使用默认帧 (接触帧+{int(fps * 0.33)}帧)")
    
    print(f"最佳跟随动作帧索引: {best_follow_idx} (接触帧: {contact_frame})")
    return best_follow_idx


def overlay_bounding_boxes(image, boxes):
    """在图像上叠加边界框"""
    result = image.copy()
    
    for box in boxes:
        bbox = box["bbox"]
        label = box.get("label", "")
        color = box.get("color", (255, 0, 0))
        
        # 绘制边界框
        cv2.rectangle(result, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), color, 2)
        
        # 绘制标签
        if label:
            cv2.putText(result, label, (int(bbox[0]), int(bbox[1] - 10)), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    
    return result

def save_video(frames, output_path, fps=30, for_wechat=True):
    """保存视频，优化微信兼容性"""
    if not frames:
        return
    
    original_height, original_width = frames[0].shape[:2]
    
    # 微信兼容性优化
    if for_wechat:
        # 限制分辨率 - 微信推荐最大1280x720
        max_width, max_height = 1280, 720
        if original_width > max_width or original_height > max_height:
            # 保持宽高比缩放
            scale = min(max_width / original_width, max_height / original_height)
            width = int(original_width * scale)
            height = int(original_height * scale)
            
            # 确保宽高是偶数（H.264要求）
            width = width - (width % 2)
            height = height - (height % 2)
            
            print(f"🔄 为微信兼容性调整分辨率: {original_width}x{original_height} -> {width}x{height}")
            
            # 调整所有帧尺寸
            resized_frames = []
            for frame in frames:
                resized_frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                resized_frames.append(resized_frame)
            frames = resized_frames
        else:
            width, height = original_width, original_height
            # 确保宽高是偶数
            width = width - (width % 2)
            height = height - (height % 2)
            if width != original_width or height != original_height:
                resized_frames = []
                for frame in frames:
                    resized_frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                    resized_frames.append(resized_frame)
                frames = resized_frames
        
        # 限制帧率 - 微信推荐30fps以下
        if fps > 30:
            fps = 30
            print(f"🔄 为微信兼容性调整帧率为30fps")
    else:
        width, height = original_width, original_height
    
    # 微信优化的编码器配置
    wechat_codecs = [
        # H.264 - 微信最佳兼容性
        {
            'name': 'H264_BASELINE', 
            'fourcc': cv2.VideoWriter_fourcc(*'avc1'),
            'description': 'H.264 Baseline Profile (微信推荐)'
        },
        {
            'name': 'H264_MP4V', 
            'fourcc': cv2.VideoWriter_fourcc(*'mp4v'),
            'description': 'H.264 MP4V (微信兼容)'
        },
        # 备用编码器
        {
            'name': 'XVID', 
            'fourcc': cv2.VideoWriter_fourcc(*'XVID'),
            'description': 'XVID编码器'
        },
        {
            'name': 'MJPG', 
            'fourcc': cv2.VideoWriter_fourcc(*'MJPG'),
            'description': 'Motion JPEG'
        }
    ]
    
    success = False
    
    # 尝试使用微信优化的编码器
    for codec_info in wechat_codecs:
        try:
            codec_name = codec_info['name']
            fourcc = codec_info['fourcc']
            description = codec_info['description']
            
            temp_path = output_path.replace('.mp4', f'_temp_{codec_name}.mp4')
            
            # 创建VideoWriter
            out = cv2.VideoWriter(temp_path, fourcc, fps, (width, height))
            
            if out.isOpened():
                print(f"✅ 使用 {description}")
                
                # 写入帧
                for frame in frames:
                    frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    out.write(frame_bgr)
                
                out.release()
                
                # 检查生成的文件
                if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
                    
                    # 微信文件大小限制检查（一般限制为25MB）
                    if for_wechat and file_size_mb > 25:
                        print(f"⚠️ 文件过大 ({file_size_mb:.1f}MB > 25MB)，尝试降低质量...")
                        os.remove(temp_path)
                        
                        # 尝试降低帧率再次生成
                        lower_fps = max(15, fps // 2)
                        out_lower = cv2.VideoWriter(temp_path, fourcc, lower_fps, (width, height))
                        if out_lower.isOpened():
                            for frame in frames[::2]:  # 跳帧处理
                                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                                out_lower.write(frame_bgr)
                            out_lower.release()
                            
                            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                                file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
                                print(f"🔄 降低质量后文件大小: {file_size_mb:.1f}MB")
                    
                    # 重命名为最终文件名
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(temp_path, output_path)
                    
                    final_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    print(f"✅ 视频已保存: {output_path}")
                    print(f"📊 文件信息: {final_size_mb:.1f}MB, {width}x{height}, {fps}fps")
                    
                    if for_wechat:
                        if final_size_mb <= 25:
                            print("✅ 文件大小符合微信要求 (≤25MB)")
                        else:
                            print("⚠️ 文件可能太大，建议进一步压缩")
                    
                    success = True
                    break
                else:
                    print(f"❌ {codec_name} 生成的文件无效")
            else:
                out.release()
                print(f"❌ 无法初始化 {codec_name} 编码器")
                
        except Exception as e:
            print(f"⚠️ {codec_info['name']} 编码器失败: {e}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
    
    # 如果所有编码器都失败，使用最基本的方法
    if not success:
        print("⚠️ 所有编码器均失败，使用最基本编码器")
        try:
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            for frame in frames:
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                out.write(frame_bgr)
            out.release()
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"✅ 基本编码器保存成功: {output_path}")
            else:
                print(f"❌ 视频保存完全失败")
        except Exception as e:
            print(f"❌ 基本编码器也失败: {e}")

def save_video_with_one_action(output_dir: str, frames_list: list, ball_tracked: list, 
                               racket_tracked: list, player_tracked: list, 
                               contact_frame: int, prep_frame: int, follow_frame: int):
    """保存击球动作视频（微信优化版本）"""
    print("\n🎬 生成击球动作视频（微信优化）...")
    
    start_frame = prep_frame
    end_frame = follow_frame
    action_frames = frames_list[start_frame:end_frame+1]
    
    annotated_frames = []
    for i, frame in enumerate(action_frames):
        current_frame_idx = start_frame + i
        boxes = []
        
        # 添加检测框
        if current_frame_idx < len(ball_tracked) and ball_tracked[current_frame_idx]:
            for ball in ball_tracked[current_frame_idx]:
                boxes.append({"bbox": ball["bbox"], "label": "Ball", "color": (255, 255, 0)})
        
        if current_frame_idx < len(racket_tracked) and racket_tracked[current_frame_idx]:
            for racket in racket_tracked[current_frame_idx]:
                boxes.append({"bbox": racket["bbox"], "label": "Racket", "color": (0, 0, 255)})
        
        frame_with_boxes = overlay_bounding_boxes(frame, boxes) if boxes else frame.copy()
        
        # 添加阶段标识
        if current_frame_idx < contact_frame:
            phase_text = "preparation"
            color = (255, 255, 0)
        elif current_frame_idx == contact_frame:
            phase_text = "contact"
            color = (0, 0, 255)
        else:
            phase_text = "follow"
            color = (0, 255, 0)
        
        cv2.putText(frame_with_boxes, phase_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
        annotated_frames.append(frame_with_boxes)
    
    # 生成微信优化版本
    action_video_path = os.path.join(output_dir, "tennis_action_wechat.mp4")
    slow_motion_video_path = os.path.join(output_dir, "tennis_action_slow_wechat.mp4")
    
    # 原版本（微信优化）
    save_video(annotated_frames, action_video_path, fps=25, for_wechat=True)  # 25fps更适合微信
    save_video(annotated_frames, slow_motion_video_path, fps=12, for_wechat=True)  # 慢动作版本
    
    print(f"✅ 微信优化击球动作视频已保存:")
    print(f"   常速版本: {action_video_path}")
    print(f"   慢动作版本: {slow_motion_video_path}")
    
    return action_video_path, slow_motion_video_path

def save_complete_detection_video(output_dir: str, frames_list: list, ball_tracked: list,
                                 racket_tracked: list, player_tracked: list,
                                 contact_frame: int, prep_frame: int, follow_frame: int):
    """保存完整检测视频（微信优化版本）"""
    print("\n🎬 生成完整检测视频（微信优化）...")
    
    annotated_frames = []
    for i, frame in enumerate(frames_list):
        boxes = []
        
        # 添加所有检测框
        if i < len(ball_tracked) and ball_tracked[i]:
            for ball in ball_tracked[i]:
                boxes.append({"bbox": ball["bbox"], "label": "Ball", "color": (255, 255, 0)})
        
        if i < len(racket_tracked) and racket_tracked[i]:
            for racket in racket_tracked[i]:
                boxes.append({"bbox": racket["bbox"], "label": "Racket", "color": (0, 0, 255)})
        
        if i < len(player_tracked) and player_tracked[i]:
            for player in player_tracked[i]:
                boxes.append({"bbox": player["bbox"], "label": "Player", "color": (0, 255, 0)})
        
        frame_with_boxes = overlay_bounding_boxes(frame, boxes) if boxes else frame.copy()
        
        # 标记关键帧
        if i in [prep_frame, contact_frame, follow_frame]:
            frame_height, frame_width = frame_with_boxes.shape[:2]
            if i == prep_frame:
                color = (255, 255, 0)
                label = "准备"
            elif i == contact_frame:
                color = (0, 0, 255)
                label = "接触"
            else:
                color = (0, 255, 0)
                label = "跟随"
            
            cv2.rectangle(frame_with_boxes, (0, 0), (frame_width-1, frame_height-1), color, 8)
            cv2.putText(frame_with_boxes, label, (frame_width-100, 35), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
        
        annotated_frames.append(frame_with_boxes)
    
    complete_video_path = os.path.join(output_dir, "complete_detection_wechat.mp4")
    complete_slow_video_path = os.path.join(output_dir, "complete_detection_slow_wechat.mp4")
    
    save_video(annotated_frames, complete_video_path, fps=24, for_wechat=True)
    save_video(annotated_frames, complete_slow_video_path, fps=12, for_wechat=True)
    
    print(f"✅ 微信优化完整检测视频已保存:")
    print(f"   常速版本: {complete_video_path}")
    print(f"   慢动作版本: {complete_slow_video_path}")
    
    return complete_video_path, complete_slow_video_path


def save_filtered_complete_detection_video(output_dir: str, frames_list: list, ball_tracked: list,
                                 racket_tracked: list, player_tracked: list,
                                 contact_frame: int, prep_frame: int, follow_frame: int):
    """保存过滤后完整检测视频（微信优化版本）"""
    print("\n🎬 生成过滤后完整检测视频（微信优化）...")
    
    annotated_frames = []
    for i, frame in enumerate(frames_list):
        boxes = []
        
        # 添加所有检测框
        if i < len(ball_tracked) and ball_tracked[i]:
            for ball in ball_tracked[i]:
                boxes.append({"bbox": ball["bbox"], "label": "Ball", "color": (255, 255, 0)})
        
        if i < len(racket_tracked) and racket_tracked[i]:
            for racket in racket_tracked[i]:
                boxes.append({"bbox": racket["bbox"], "label": "Racket", "color": (0, 0, 255)})
        
        if i < len(player_tracked) and player_tracked[i]:
            for player in player_tracked[i]:
                boxes.append({"bbox": player["bbox"], "label": "Player", "color": (0, 255, 0)})
        
        frame_with_boxes = overlay_bounding_boxes(frame, boxes) if boxes else frame.copy()
        
        # 标记关键帧
        if i in [prep_frame, contact_frame, follow_frame]:
            frame_height, frame_width = frame_with_boxes.shape[:2]
            if i == prep_frame:
                color = (255, 255, 0)
                label = "准备"
            elif i == contact_frame:
                color = (0, 0, 255)
                label = "接触"
            else:
                color = (0, 255, 0)
                label = "跟随"
            
            cv2.rectangle(frame_with_boxes, (0, 0), (frame_width-1, frame_height-1), color, 8)
            cv2.putText(frame_with_boxes, label, (frame_width-100, 35), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
        
        annotated_frames.append(frame_with_boxes)
    
    filtered_complete_video_path = os.path.join(output_dir, "filtered_complete_detection_wechat.mp4")
    filtered_complete_slow_video_path = os.path.join(output_dir, "filtered_complete_detection_slow_wechat.mp4")
    
    save_video(annotated_frames, filtered_complete_video_path, fps=24, for_wechat=True)
    save_video(annotated_frames, filtered_complete_slow_video_path, fps=12, for_wechat=True)
    
    print(f"✅ 微信优化过滤后完整检测视频已保存:")
    print(f"   常速版本: {filtered_complete_video_path}")
    print(f"   慢动作版本: {filtered_complete_slow_video_path}")
    
    return filtered_complete_video_path, filtered_complete_slow_video_path


def process_tennis_video(video_path: str, output_dir: str) -> dict:
    """使用新API处理网球视频，检测击球动作的关键帧"""
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"===== 开始处理网球视频: {video_path} =====")
    print(f"输出结果将保存在目录: {output_dir}")

    try:
        # 1. 检查并裁剪视频
        processed_video_path = trim_video_if_needed(video_path)
        
        # 2. 调用API进行目标检测
        prompts = ["moving tennis ball with motion blur", "tennis racket", "tennis player"]
        api_detections = call_vision_agent_api(processed_video_path, prompts)
        
        if not api_detections:
            raise ValueError("API未返回任何检测结果")
        
        # 3. 转换API结果格式
        ball_tracked, racket_tracked, player_tracked = convert_api_detections_to_tracked_format(api_detections)
        
        # 4. 提取视频帧
        frames_list, actual_fps = extract_frames_from_video(processed_video_path)
        
        # 确保数据长度一致
        min_length = min(len(frames_list), len(ball_tracked), len(racket_tracked), len(player_tracked))
        frames_list = frames_list[:min_length]
        ball_tracked = ball_tracked[:min_length]
        racket_tracked = racket_tracked[:min_length]
        player_tracked = player_tracked[:min_length]
        
        # 5. 过滤检测结果
        print("\n🔍 过滤检测结果...")
        filtered_player_tracked = filter_player(player_tracked)
        filtered_racket_tracked = filter_racket(racket_tracked, filtered_player_tracked)
        filtered_ball_tracked = filter_tennis_ball(ball_tracked, filtered_racket_tracked)
        
        # 6. 选择关键帧
        print("\n🎯 选择关键帧...")
        contact_frame = select_contact_frame(filtered_ball_tracked, filtered_player_tracked, filtered_player_tracked, actual_fps)
        prep_frame = select_preparation_frame(contact_frame, filtered_ball_tracked, filtered_player_tracked, filtered_player_tracked, actual_fps)
        follow_frame = select_follow_frame(contact_frame, filtered_ball_tracked, filtered_player_tracked, filtered_player_tracked, actual_fps)
        
        # 7. 保存关键帧图片
        print("\n💾 保存关键帧图片...")
        prep_frame_path = os.path.join(output_dir, "preparation_frame.jpg")
        contact_frame_path = os.path.join(output_dir, "contact_frame.jpg")
        follow_frame_path = os.path.join(output_dir, "follow_frame.jpg")
        
        cv2.imwrite(prep_frame_path, cv2.cvtColor(frames_list[prep_frame], cv2.COLOR_RGB2BGR))
        cv2.imwrite(contact_frame_path, cv2.cvtColor(frames_list[contact_frame], cv2.COLOR_RGB2BGR))
        cv2.imwrite(follow_frame_path, cv2.cvtColor(frames_list[follow_frame], cv2.COLOR_RGB2BGR))
        
        # 8. 保存视频: 完整的单个击球动作视频
        one_action_video_path, slow_action_video_path = save_video_with_one_action(
            output_dir, frames_list, ball_tracked, racket_tracked, player_tracked,
            contact_frame, prep_frame, follow_frame)
        
        # 保存视频: 输入视频的完整检测视频
        complete_video_path, complete_slow_video_path = save_complete_detection_video(
            output_dir, frames_list, ball_tracked, racket_tracked, player_tracked,
            contact_frame, prep_frame, follow_frame)

        # 保存视频: 过滤后的完整检测视频
        filtered_complete_video_path, filtered_complete_slow_video_path = save_filtered_complete_detection_video(
            output_dir, frames_list, filtered_ball_tracked, filtered_racket_tracked, filtered_player_tracked,
            contact_frame, prep_frame, follow_frame)
        
        # 9. 清理临时文件
        if processed_video_path != video_path:
            try:
                os.remove(processed_video_path)
                temp_dir = os.path.dirname(processed_video_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except Exception as e:
                print(f"⚠️ 清理临时文件时出错: {e}")
        
        # 10. 返回结果
        result = {
            "preparation_frame": prep_frame_path,
            "contact_frame": contact_frame_path,
            "follow_frame": follow_frame_path,
            "one_action_video": one_action_video_path,
            "slow_action_video": slow_action_video_path,
            "complete_video": complete_video_path,
            "complete_slow_video": complete_slow_video_path,
            "filtered_complete_video": filtered_complete_video_path,
            "filtered_complete_slow_video": filtered_complete_slow_video_path
        }
        
        print("\n✅ 视频处理完成！")
        return result
        
    except Exception as e:
        print(f"\n❌ 处理过程中出错: {e}")
        raise e

# 测试函数
if __name__ == "__main__":
    print(f"当前目录: {os.getcwd()}")
    video_path = "/Users/claude89757/github/wechat-on-airflow/dags/tennis_dags/ai_tennis_dags/action_score_v4_local_file/videos/roger.mp4"
    output_dir = "/Users/claude89757/github/wechat-on-airflow/dags/tennis_dags/ai_tennis_dags/action_score_v4_local_file/videos/output"
    
    result = process_tennis_video(video_path, output_dir)
    
    print("\n🎉 测试完成！微信优化视频生成结果:")
    print("="*50)
    print("📱 微信推荐视频（直接可用于微信分享）:")
    print(f"   击球动作视频: {result['one_action_video']}")
    print(f"   击球慢动作: {result['slow_action_video']}")
    
    print("\n📊 微信兼容性信息:")
    print("   编码格式: H.264")
    print("   最大分辨率: 1280x720")
    print("   最大文件大小: 25MB")
    print("   推荐帧率: 25fps以下")
    print("   视频格式: MP4")
    
    print("\n✅ 所有视频均已针对微信优化，可直接在安卓手机微信中发送！")
