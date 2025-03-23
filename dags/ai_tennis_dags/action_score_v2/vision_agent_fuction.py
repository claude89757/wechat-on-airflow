#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import os
from airflow.models import Variable
from contextlib import contextmanager


@contextmanager
def proxy_context():
    """
    代理设置的上下文管理器
    """
    # 保存原始代理设置
    original_http_proxy = os.environ.get('HTTP_PROXY')
    original_https_proxy = os.environ.get('HTTPS_PROXY')
    
    try:
        # 设置新代理
        proxy_url = Variable.get("PROXY_URL", default_var="")
        if proxy_url:
            os.environ['HTTPS_PROXY'] = proxy_url
            os.environ['HTTP_PROXY'] = proxy_url
        else:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
        yield
    finally:
        # 恢复原始代理
        if original_http_proxy:
            os.environ['HTTP_PROXY'] = original_http_proxy
        else:
            os.environ.pop('HTTP_PROXY', None)
            
        if original_https_proxy:
            os.environ['HTTPS_PROXY'] = original_https_proxy
        else:
            os.environ.pop('HTTPS_PROXY', None)


def process_tennis_video(video_path: str, output_path: str = "./output") -> dict:
    """
    Processes a tennis video to find a complete stroke that includes
    a contact moment between the player's tennis racket and the moving ball. 
    It returns a dictionary with paths to three key frames (preparation, contact, follow) 
    and the path to the short stroke video clip.

    Parameters
    ----------
    video_path : str
        The path to the tennis video file.

    Returns
    -------
    dict
        A dictionary containing:
        {
            "preparation_frame": str,
            "contact_frame": str,
            "follow_frame": str,
            "stroke_video": str
        }
    """
    import os
    import math
    import cv2
    from datetime import datetime
    from pillow_heif import register_heif_opener
    import vision_agent as va
    from vision_agent.tools import (
        extract_frames_and_timestamps,
        save_image,
        save_video,
        overlay_bounding_boxes,
        owlv2_sam2_video_tracking
    )

    register_heif_opener()

    # 创建唯一的输出目录
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_name = os.path.basename(video_path).split('.')[0]
    output_dir = f"{output_path}/{video_name}_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    
    # 创建帧存储子目录
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    print(f"===== 开始处理网球视频: {video_path} =====")
    print(f"输出结果将保存在目录: {output_dir}")

    #########################################
    # 辅助函数定义
    #########################################
    
    # ===== 基础工具函数 =====
    def get_bbox_center(bbox):
        """计算边界框中心点（归一化坐标 [xmin, ymin, xmax, ymax]）"""
        return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)

    def euclidean_distance(p1, p2):
        """计算两个2D点之间的欧几里得距离"""
        return math.dist(p1, p2)
    
    def bbox_iou(box1, box2):
        """计算两个边界框的IoU（交并比）"""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0
    
    # ===== 网球检测和分析函数 =====
    def is_motion_consistent(positions, min_velocity=0.005):
        """判断运动是否连贯一致，用于过滤跳跃性错误检测"""
        if len(positions) < 3:
            return False
            
        velocities = []
        for i in range(1, len(positions)):
            prev_pos = positions[i-1]
            curr_pos = positions[i]
            velocity = euclidean_distance(prev_pos, curr_pos)
            velocities.append(velocity)
            
        # 检查是否有足够的运动
        if max(velocities) < min_velocity:
            return False
            
        # 检查运动的连贯性 (相邻速度变化不应过大)
        for i in range(1, len(velocities)):
            ratio = max(velocities[i], velocities[i-1]) / (min(velocities[i], velocities[i-1]) + 0.00001)
            # 对于重影球，允许更大的速度变化
            if ratio > 8.0:  # 增大阈值以适应重影导致的位置突变
                return False
                
        return True
        
    def is_motion_blur_ball(bbox, aspect_ratio_threshold=2.0):
        """判断边界框是否可能是重影网球（通常有更大的宽高比）"""
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        
        # 避免除零错误
        if height < 0.001:
            return False
            
        aspect_ratio = width / height
        # 重影网球通常更扁平（水平运动）或更细长（垂直运动）
        return aspect_ratio > aspect_ratio_threshold or aspect_ratio < (1/aspect_ratio_threshold)
    
    # ===== 轨迹分析和评分函数 =====
    def compute_track_movement_score(track_data, sizes):
        """计算轨迹的综合评分：考虑运动量、一致性和检测数量"""
        if len(track_data) < 2:  # 降低最小检测点要求，对于网球可能只有几帧能检测到
            return 0.0
            
        # 提取位置列表用于运动一致性检查
        positions = [center for _, center, _, _ in track_data]
        
        # 修改：检查帧索引序列中是否有大的间隔
        frame_indices = [f for f, _, _, _ in track_data]
        max_frame_gap = 0
        for i in range(1, len(frame_indices)):
            gap = frame_indices[i] - frame_indices[i-1]
            max_frame_gap = max(max_frame_gap, gap)
        
        # 添加：对于网球，即使检测点很少也给予较高评分
        is_ball_track = len(track_data) < 10  # 假设检测点较少的是网球轨迹
        
        # 添加：为间歇性网球轨迹创建特定的评分逻辑
        gap_penalty = 1.0
        if max_frame_gap > 5:  # 如果有较大的帧间隔
            gap_penalty = 0.9
        
        # 考虑运动一致性，对于网球宽松处理
        motion_penalty = 1.0
        if len(positions) >= 3 and not is_motion_consistent(positions):
            # 对于网球，不太惩罚运动不一致
            motion_penalty = 0.9 if is_ball_track else 0.85
            
        total_movement = 0.0
        avg_confidence = 0.0
        for j in range(1, len(track_data)):
            _, prev_center, _, prev_conf = track_data[j - 1]
            _, curr_center, _, curr_conf = track_data[j]
            dist = euclidean_distance(prev_center, curr_center)
            # 考虑时间间隔，计算速度
            frame_diff = track_data[j][0] - track_data[j-1][0]
            if frame_diff > 0:
                speed = dist / frame_diff
                # 放宽网球速度范围
                speed_range_ok = True
                if not is_ball_track and (speed < 0.0005 or speed > 0.35):
                    speed_range_ok = False
                
                if speed_range_ok:
                    total_movement += dist
            else:
                total_movement += dist
                
            avg_confidence += (prev_conf + curr_conf) / 2
            
        avg_confidence = avg_confidence / (len(track_data) - 1) if len(track_data) > 1 else 0
        
        # 计算尺寸一致性 - 真实物体尺寸变化不会太剧烈
        size_consistency = 1.0 - (max(sizes) - min(sizes)) / max(sizes) if max(sizes) > 0 else 0
        
        # 调整权重因子，对网球有特殊处理
        if is_ball_track:
            # 网球轨迹：即使检测点少也给高分
            movement_weight = 0.3
            consistency_weight = 0.1
            detection_count_weight = 0.5  # 极大增强检测数量的权重
            confidence_weight = 0.1
        else:
            # 球拍轨迹：保持正常权重
            movement_weight = 0.5
            consistency_weight = 0.1
            detection_count_weight = 0.3
            confidence_weight = 0.1
        
        # 综合评分，考虑间隔惩罚
        score = (movement_weight * total_movement + 
                 consistency_weight * size_consistency + 
                 detection_count_weight * len(track_data) + 
                 confidence_weight * avg_confidence) * motion_penalty * gap_penalty
                 
        # 为稀少的网球检测加分
        if is_ball_track and len(track_data) > 0:
            # 额外奖励：即使网球只检测到很少的点，也要确保它能被选中
            score += 2.0
                 
        return score
    
    # ===== 轨迹插值函数 =====
    def interpolate_missing_frames(data_dict, total_frames):
        """线性插值缺失帧的位置和边界框"""
        if not data_dict:
            return data_dict, 0
            
        all_frames = sorted(data_dict.keys())
        if len(all_frames) < 2:
            return data_dict, 0
            
        result = dict(data_dict)  # 复制原始数据
        
        # 修改：找出所有合理的连续段
        segments = []
        current_segment = [all_frames[0]]
        
        for i in range(1, len(all_frames)):
            # 对重影球允许更大的帧间隔
            if all_frames[i] - all_frames[i-1] <= 15:  # 增大允许的间隔，适应重影球可能造成的检测间断
                current_segment.append(all_frames[i])
            else:
                segments.append(current_segment)
                current_segment = [all_frames[i]]
        
        if current_segment:
            segments.append(current_segment)
            
        print(f"  检测到 {len(segments)} 个连续的网球轨迹段")
        
        # 只在每个合理的段内进行插值
        interpolated_count = 0
        for segment in segments:
            seg_start = min(segment)
            seg_end = max(segment)
            
            for f in range(seg_start, seg_end + 1):
                if f in result:
                    continue  # 已有数据，跳过
                    
                # 寻找最近的前后帧
                prev_frames = [pf for pf in segment if pf < f]
                next_frames = [nf for nf in segment if nf > f]
                
                if not prev_frames or not next_frames:
                    continue  # 无法插值
                    
                prev_f = max(prev_frames)
                next_f = min(next_frames)
                
                # 限制插值的最大间隔，但对于重影球放宽限制
                max_allowed_gap = 8  # 增大最大允许的插值间隔
                if next_f - prev_f > max_allowed_gap:
                    continue
                    
                # 时间权重：f与prev_f和next_f之间的相对位置
                weight = (f - prev_f) / (next_f - prev_f)
                
                # 获取前后帧的数据
                prev_center, prev_bbox, prev_conf = data_dict[prev_f]
                next_center, next_bbox, next_conf = data_dict[next_f]
                
                # 检查是否有重影特征
                prev_is_blur = is_motion_blur_ball(prev_bbox)
                next_is_blur = is_motion_blur_ball(next_bbox)
                
                # 如果两帧都是重影帧，使用更复杂的插值策略
                if prev_is_blur and next_is_blur:
                    # 计算运动方向
                    motion_dir_x = next_center[0] - prev_center[0]
                    motion_dir_y = next_center[1] - prev_center[1]
                    
                    # 对于重影球，根据运动方向调整插值，使边界框在运动方向上更长
                    # 线性插值中心点
                    new_center = (
                        prev_center[0] + weight * motion_dir_x,
                        prev_center[1] + weight * motion_dir_y
                    )
                    
                    # 计算边界框的主轴方向
                    if abs(motion_dir_x) > abs(motion_dir_y):
                        # 水平运动占主导
                        bbox_stretch = 1.2  # 在运动方向上拉伸边界框
                        new_bbox = [
                            prev_bbox[0] + weight * (next_bbox[0] - prev_bbox[0]),
                            prev_bbox[1] + weight * (next_bbox[1] - prev_bbox[1]),
                            prev_bbox[2] + weight * (next_bbox[2] - prev_bbox[2]) * bbox_stretch,
                            prev_bbox[3] + weight * (next_bbox[3] - prev_bbox[3])
                        ]
                    else:
                        # 垂直运动占主导
                        bbox_stretch = 1.2
                        new_bbox = [
                            prev_bbox[0] + weight * (next_bbox[0] - prev_bbox[0]),
                            prev_bbox[1] + weight * (next_bbox[1] - prev_bbox[1]),
                            prev_bbox[2] + weight * (next_bbox[2] - prev_bbox[2]),
                            prev_bbox[3] + weight * (next_bbox[3] - prev_bbox[3]) * bbox_stretch
                        ]
                else:
                    # 标准线性插值
                    new_center = (
                        prev_center[0] + weight * (next_center[0] - prev_center[0]),
                        prev_center[1] + weight * (next_center[1] - prev_center[1])
                    )
                    
                    # 线性插值边界框
                    new_bbox = [
                        prev_bbox[0] + weight * (next_bbox[0] - prev_bbox[0]),
                        prev_bbox[1] + weight * (next_bbox[1] - prev_bbox[1]),
                        prev_bbox[2] + weight * (next_bbox[2] - prev_bbox[2]),
                        prev_bbox[3] + weight * (next_bbox[3] - prev_bbox[3])
                    ]
                
                # 线性插值置信度，保持插值帧的较高置信度
                new_conf = (prev_conf + next_conf) / 2
                if prev_is_blur or next_is_blur:
                    # 若相邻帧有重影，提高插值帧的置信度
                    new_conf = new_conf * 0.95  # 轻微降低，但幅度更小
                else:
                    new_conf = new_conf * 0.9  # 标准插值帧的置信度降低
                
                # 添加到结果中
                result[f] = (new_center, new_bbox, new_conf)
                interpolated_count += 1
            
        return result, interpolated_count
    
    # ===== 可视化函数 =====
    def overlay_racket_ball(frame_idx, frame):
        # 增强边界框的可视化效果
        enhanced_frame = frame.copy()
        boxes = []
        
        ball_count = 0
        racket_count = 0
        
        # 收集要显示的边界框
        for det in tracked[frame_idx]:
            is_ball = "ball" in det["label"].lower()
            is_racket = "racket" in det["label"].lower() or "tennis racket" in det["label"].lower()
            
            if is_ball or is_racket:
                boxes.append(det)
                
                if is_ball:
                    ball_count += 1
                elif is_racket:
                    racket_count += 1
                
                # 增强置信度显示
                lbl = det["label"]
                conf = det.get("confidence", 0)
                bbox = det["bbox"]
                
                # 转换边界框到像素坐标
                h, w = frame.shape[:2]
                x1, y1 = int(bbox[0] * w), int(bbox[1] * h)
                x2, y2 = int(bbox[2] * w), int(bbox[3] * h)
                
                # 计算边界框中心
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                
                # 根据类型设置不同颜色
                if is_ball:
                    color = (0, 255, 255)  # 黄色
                    text = f"Ball: {conf:.2f}"
                    # 对网球增加额外的高亮效果
                    cv2.circle(enhanced_frame, (cx, cy), 10, (0, 0, 255), 2)
                    # 打印网球坐标信息
                    if frame_idx in ball_data:
                        cv2.putText(enhanced_frame, f"Tracked Ball", (x1, y1-20), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                else:
                    color = (0, 255, 0)  # 绿色
                    text = f"Racket: {conf:.2f}"
                
                # 绘制中心点十字线
                cv2.line(enhanced_frame, (cx-10, cy), (cx+10, cy), color, 2)
                cv2.line(enhanced_frame, (cx, cy-10), (cx, cy+10), color, 2)
                
                # 绘制置信度文本
                font_scale = 0.5
                font_thickness = 1
                text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]
                cv2.putText(enhanced_frame, text, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, font_thickness)
        
        # 在帧上添加统计信息
        frame_info = f"Frame {frame_idx}: {ball_count} balls, {racket_count} rackets"
        cv2.putText(enhanced_frame, frame_info, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        # 标记是否是在跟踪的帧
        if frame_idx in ball_data:
            b_center, b_bbox, b_conf = ball_data[frame_idx]
            bx, by = int(b_center[0] * w), int(b_center[1] * h)
            cv2.circle(enhanced_frame, (bx, by), 15, (255, 0, 0), 3)
            cv2.putText(enhanced_frame, f"Ball Track (conf:{b_conf:.2f})", (bx+20, by), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
        
        # 使用原始函数叠加标准边界框
        result = overlay_bounding_boxes(enhanced_frame, boxes)
        return result

    # 从这里开始是主要处理逻辑
    #########################################
    # 1. 视频帧提取
    #########################################
    print("\n步骤1: 从视频中提取帧...")
    frames_data = extract_frames_and_timestamps(video_path, fps=60)
    frames_list = [f["frame"] for f in frames_data]
    print(f"  提取了 {len(frames_list)} 帧")

    #########################################
    # 2. 网球和球拍检测与跟踪
    #########################################
    print("\n步骤2: 使用目标检测和跟踪模型...")

    with proxy_context():
        # 使用更精确的提示词，专注于运动中、带拖影、模糊的网球
        tennis_ball_prompt = "fast moving tennis ball with motion blur"
        print(f"  使用网球检测提示: '{tennis_ball_prompt}'")
        ball_tracked = owlv2_sam2_video_tracking(tennis_ball_prompt, frames_list, box_threshold=0.4, chunk_length=8)
        
        # 使用球拍检测提示
        racket_prompt = "tennis racket"
        print(f"  使用球拍检测提示: '{racket_prompt}'")
        racket_tracked = owlv2_sam2_video_tracking(racket_prompt, frames_list, box_threshold=0.6, chunk_length=15)
    
    # 合并球和拍的检测结果
    tracked = []
    for i in range(len(frames_list)):
        frame_detections = []
        # 添加球的检测结果
        if i < len(ball_tracked):
            frame_detections.extend(ball_tracked[i])
        # 添加球拍的检测结果
        if i < len(racket_tracked):
            frame_detections.extend(racket_tracked[i])
        tracked.append(frame_detections)
    
    print(f"  跟踪完成，检查每帧的检测结果")

    #########################################
    # 3. 过滤和整理检测结果
    #########################################
    print("\n步骤3: 过滤和整理检测结果...")
    
    # 初始化跟踪数据结构
    ball_tracks = {}    # 网球轨迹字典：track_id -> 轨迹点列表
    racket_tracks = {}  # 球拍轨迹字典：track_id -> 轨迹点列表
    ball_sizes = {}     # 网球大小记录：track_id -> 大小列表
    racket_sizes = {}   # 球拍大小记录：track_id -> 大小列表
    ball_detection_count = 0  # 网球检测总数
    racket_detection_count = 0  # 球拍检测总数

    # 统计网球检测帧
    frames_with_ball = set()
    for i, preds in enumerate(tracked):
        for det in preds:
            if "ball" in det["label"].lower():
                frames_with_ball.add(i)
                break
    
    print(f"  在{len(frames_list)}帧中，有{len(frames_with_ball)}帧检测到网球")
    
    if frames_with_ball:
        print("  检测到网球的帧索引列表:")
        print("  ", sorted(list(frames_with_ball)))
    else:
        print("  没有检测到任何网球！")
    
    # 处理每一帧的检测结果，分离球和拍的轨迹
    for i, preds in enumerate(tracked):
        for det in preds:
            lbl_lower = det["label"].lower()
            bbox = det["bbox"]
            bbox_center = get_bbox_center(bbox)
            track_id = det["label"].split(":")[0]
            
            # 计算边界框面积
            bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            
            if "ball" in lbl_lower:
                # 进一步放宽网球的面积过滤条件
                if 0.0001 < bbox_area < 0.08:  # 极度放宽网球尺寸范围
                    confidence = det.get("confidence", 0.5)  # 获取置信度，默认0.5
                    
                    # 检查是否可能是重影网球，如果是则提高置信度
                    is_blur_ball = is_motion_blur_ball(bbox)
                    if is_blur_ball:
                        # 对于重影网球，增强置信度
                        confidence = min(1.0, confidence * 1.2)
                        
                    # 极低的网球置信度阈值
                    min_conf = 0.1
                    if confidence >= min_conf:
                        ball_tracks.setdefault(track_id, []).append((i, bbox_center, bbox, confidence))
                        ball_sizes.setdefault(track_id, []).append(bbox_area)
                        ball_detection_count += 1
            elif "racket" in lbl_lower or "tennis racket" in lbl_lower:
                confidence = det.get("confidence", 0.5)
                # 降低球拍的置信度阈值
                if confidence >= 0.2:
                    racket_tracks.setdefault(track_id, []).append((i, bbox_center, bbox, confidence))
                    racket_sizes.setdefault(track_id, []).append(bbox_area)
                    racket_detection_count += 1
    
    print(f"  检测到 {ball_detection_count} 个网球实例，分布在 {len(ball_tracks)} 个可能的轨迹中")
    print(f"  检测到 {racket_detection_count} 个球拍实例，分布在 {len(racket_tracks)} 个可能的轨迹中")
    
    # 打印网球轨迹详情
    if len(ball_tracks) > 0:
        print("\n  网球轨迹详细信息:")
        for track_id, track in ball_tracks.items():
            print(f"  网球轨迹 {track_id}: {len(track)} 个实例，在帧 {track[0][0]} 到 {track[-1][0]}")
            print(f"    帧索引: ", end="")
            frames_in_track = [f for f, _, _, _ in track]
            
            # 如果帧太多，只打印部分
            if len(frames_in_track) > 20:
                print(f"{frames_in_track[:10]} ... {frames_in_track[-10:]} (共{len(frames_in_track)}帧)")
            else:
                print(frames_in_track)
                
            # 打印置信度范围
            confidences = [conf for _, _, _, conf in track]
            print(f"    置信度范围: {min(confidences):.3f} - {max(confidences):.3f}, 平均: {sum(confidences)/len(confidences):.3f}")
    
    # 打印球拍轨迹详情
    if len(racket_tracks) > 0:
        print("\n  球拍轨迹详细信息:")
        for track_id, track in racket_tracks.items():
            print(f"  球拍轨迹 {track_id}: {len(track)} 个实例，在帧 {track[0][0]} 到 {track[-1][0]}")

    #########################################
    # 4. 网球未检测到时的备用方法
    #########################################
    if not ball_tracks:
        print("\n未检测到网球，尝试使用备用方法...")
        # 备用方法：根据大小和位置推测潜在的网球
        potential_ball_tracks = {}
        potential_ball_id = 0
        
        # 遍历所有帧，检查是否有可能是网球的小物体
        for i, preds in enumerate(tracked):
            for det in preds:
                bbox = det["bbox"]
                bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                bbox_center = get_bbox_center(bbox)
                confidence = det.get("confidence", 0.3)
                
                # 只检查小物体，可能是网球
                if 0.0001 < bbox_area < 0.03 and confidence > 0.2:
                    track_id = f"potential_ball_{potential_ball_id}"
                    potential_ball_tracks.setdefault(track_id, []).append((i, bbox_center, bbox, 0.3))
                    potential_ball_id += 1
        
        if potential_ball_tracks:
            print(f"  检测到 {len(potential_ball_tracks)} 个潜在网球轨迹")
            # 使用这些潜在的网球替代正常的网球轨迹
            ball_tracks = potential_ball_tracks
            
            # 重新计算大小数据
            ball_sizes = {}
            for tid, track in ball_tracks.items():
                ball_sizes[tid] = [(bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) for (_, _, bbox, _) in track]
                
            # 更新球检测计数
            ball_detection_count = sum(len(track) for track in ball_tracks.values())
            
            print(f"  使用备用方法检测到 {ball_detection_count} 个网球实例")
    
    # 检查是否有足够的网球和球拍轨迹
    if not ball_tracks or not racket_tracks:
        print("\n未检测到足够的网球或球拍，无法继续处理")
        # 如果没有检测到，返回空结果
        return {
            "preparation_frame": "",
            "contact_frame": "",
            "follow_frame": "",
            "stroke_video": "",
            "output_directory": output_dir
        }

    #########################################
    # 5. 评估轨迹质量和选择最佳轨迹
    #########################################
    print("\n步骤4: 评估检测轨迹质量...")
    # 使用改进的运动分析选择最可能的球和球拍
    ball_scores = {}
    racket_scores = {}
    
    # 计算每个网球轨迹的评分
    for tid in ball_tracks.keys():
        # 检查此轨迹是否包含重影球
        has_motion_blur = any(is_motion_blur_ball(bbox) for _, _, bbox, _ in ball_tracks[tid])
        
        score = compute_track_movement_score(ball_tracks[tid], ball_sizes.get(tid, [0]))
        
        # 对于包含重影球的轨迹，提高评分
        if has_motion_blur:
            score *= 1.2  # 提高20%的评分
            print(f"  网球轨迹 {tid} 包含重影球，提高评分")
            
        ball_scores[tid] = score
        print(f"  网球轨迹 {tid} 得分: {score:.4f}")
    
    # 计算每个球拍轨迹的评分
    for tid in racket_tracks.keys():
        score = compute_track_movement_score(racket_tracks[tid], racket_sizes.get(tid, [0]))
        racket_scores[tid] = score
        print(f"  球拍轨迹 {tid} 得分: {score:.4f}")
    
    # 选择得分最高的网球和球拍轨迹
    active_ball_id = max(ball_tracks.keys(), 
                        key=lambda tid: ball_scores[tid])
    active_racket_id = max(racket_tracks.keys(), 
                         key=lambda tid: racket_scores[tid])
    
    print(f"  选择最佳网球轨迹: {active_ball_id}，得分: {ball_scores[active_ball_id]:.4f}")
    print(f"  选择最佳球拍轨迹: {active_racket_id}，得分: {racket_scores[active_racket_id]:.4f}")

    # 转换为词典以便快速查找: frame_idx -> (center, bbox, confidence)
    ball_data = {f: (c, b, conf) for (f, c, b, conf) in ball_tracks[active_ball_id]}
    racket_data = {f: (c, b, conf) for (f, c, b, conf) in racket_tracks[active_racket_id]}
    
    print(f"  网球在 {len(ball_data)} 帧中被检测到")
    print(f"  球拍在 {len(racket_data)} 帧中被检测到")
    print(f"  共有 {len(set(ball_data.keys()) & set(racket_data.keys()))} 帧同时包含网球和球拍")

    #########################################
    # 6. 轨迹插值，填补检测漏洞
    #########################################
    print("\n步骤5: 执行轨迹插值，填补检测漏洞...")
    
    # 执行插值
    ball_data_original_len = len(ball_data)
    ball_data, ball_interpolated = interpolate_missing_frames(ball_data, len(frames_list))
    print(f"  网球轨迹: 从 {ball_data_original_len} 帧扩充到 {len(ball_data)} 帧，插值了 {ball_interpolated} 帧")
    
    # 打印插值后的帧索引
    if ball_data:
        print("  插值后的网球帧索引:")
        ball_frames_sorted = sorted(ball_data.keys())
        
        # 如果帧太多，只打印部分
        if len(ball_frames_sorted) > 30:
            print(f"  {ball_frames_sorted[:15]} ... {ball_frames_sorted[-15:]} (共{len(ball_frames_sorted)}帧)")
        else:
            print("  ", ball_frames_sorted)
    
    # 分析网球轨迹的分段情况
    if ball_data:
        ball_frames = sorted(ball_data.keys())
        segment_count = 1
        max_gap = 0
        for i in range(1, len(ball_frames)):
            gap = ball_frames[i] - ball_frames[i-1]
            max_gap = max(max_gap, gap)
            if gap > 5:  # 超过5帧的间隔视为新段
                segment_count += 1
        
        print(f"  网球轨迹分析: 共有约 {segment_count} 个不连续的轨迹段，最大帧间隔为 {max_gap}")
        
        # 如果有多个轨迹段，尝试找出最可能的击球段
        if segment_count > 1:
            segment_start = 0
            current_seg_size = 0
            best_segment = []
            best_segment_size = 0
            
            for i in range(1, len(ball_frames)):
                if ball_frames[i] - ball_frames[i-1] <= 5:
                    current_seg_size += 1
                else:
                    # 记录当前段
                    segment = ball_frames[segment_start:i]
                    if current_seg_size > best_segment_size:
                        best_segment = segment
                        best_segment_size = current_seg_size
                    # 开始新段
                    segment_start = i
                    current_seg_size = 0
            
            # 检查最后一段
            segment = ball_frames[segment_start:]
            if len(segment) > best_segment_size:
                best_segment = segment
            
            if best_segment:
                print(f"  最大的连续网球轨迹段: 帧 {min(best_segment)} 到 {max(best_segment)}，包含 {len(best_segment)} 帧")

    #########################################
    # 7. 分析球的运动轨迹和速度变化
    #########################################
    print("\n步骤6: 分析球的运动轨迹和速度变化...")
    contact_frame_candidates = []
    
    # 提取球的轨迹信息以分析运动模式
    ball_pos_frames = sorted([(f, c) for f, (c, _, _) in ball_data.items()])
    
    # 分析球的运动轨迹变化，寻找速度突变点，这通常发生在击球时
    ball_velocities = []
    for i in range(1, len(ball_pos_frames)):
        prev_idx, prev_center = ball_pos_frames[i-1]
        curr_idx, curr_center = ball_pos_frames[i]
        
        # 忽略相距太远的帧之间的速度计算（针对间歇性网球）
        if curr_idx - prev_idx > 5:
            print(f"  忽略帧 {prev_idx} 到 {curr_idx} 之间的速度计算，间隔过大")
            continue
            
        # 计算速度矢量
        velocity = (
            (curr_center[0] - prev_center[0]) / max(1, curr_idx - prev_idx),
            (curr_center[1] - prev_center[1]) / max(1, curr_idx - prev_idx)
        )
        speed = math.sqrt(velocity[0]**2 + velocity[1]**2)
        ball_velocities.append((prev_idx, curr_idx, velocity, speed))
    
    # 打印速度信息
    if ball_velocities:
        avg_speed = sum(v[3] for v in ball_velocities) / len(ball_velocities)
        max_speed = max(v[3] for v in ball_velocities)
        print(f"  网球平均速度: {avg_speed:.6f}，最大速度: {max_speed:.6f}")

    #########################################
    # 8. 寻找速度变化显著的点（可能的接触点）
    #########################################
    print("\n步骤7: 寻找速度变化显著的点...")
    velocity_changes = []
    for i in range(1, len(ball_velocities)):
        prev_vel = ball_velocities[i-1][2]
        curr_vel = ball_velocities[i][2]
        _, curr_end_idx, _, _ = ball_velocities[i]
        
        # 计算速度方向变化
        dot_product = prev_vel[0]*curr_vel[0] + prev_vel[1]*curr_vel[1]
        prev_mag = math.sqrt(prev_vel[0]**2 + prev_vel[1]**2)
        curr_mag = math.sqrt(curr_vel[0]**2 + curr_vel[1]**2)
        
        if prev_mag > 0 and curr_mag > 0:
            cos_angle = dot_product / (prev_mag * curr_mag)
            cos_angle = max(-1.0, min(1.0, cos_angle))  # 确保在有效范围内
            angle_change = math.acos(cos_angle)
            
            # 速度大小变化
            speed_change = abs(ball_velocities[i][3] - ball_velocities[i-1][3])
            
            # 综合方向和速度变化
            change_score = angle_change + speed_change * 5.0
            velocity_changes.append((curr_end_idx, change_score))
            
            if change_score > 0.5:  # 只打印显著变化
                print(f"  帧 {curr_end_idx}: 角度变化={angle_change:.2f}弧度, 速度变化={speed_change:.6f}, 综合得分={change_score:.2f}")

    #########################################
    # 9. 评估接触帧候选
    #########################################
    print("\n步骤8: 评估接触帧候选...")
    # 评估每一帧的接触可能性
    significant_candidates = []
    
    # 定义函数：选择最佳接触帧
    def find_best_contact_frame(frames_list, ball_data, racket_data, velocity_changes):
        """
        选择最佳接触帧（网球和球拍最靠近但尚未接触或重合的瞬间）
        
        参数:
        frames_list: 视频帧列表
        ball_data: 网球数据字典 {frame_idx: (center, bbox, conf)}
        racket_data: 球拍数据字典 {frame_idx: (center, bbox, conf)}
        velocity_changes: 速度变化列表 [(frame_idx, change_score)]
        
        返回:
        tuple: (最佳接触帧索引, 接触帧得分, 附近网球帧数)
        """
        contact_frame_candidates = []
        significant_candidates = []
        
        # 评估每一帧的接触可能性
        for f_idx in range(len(frames_list)):
            if f_idx in ball_data and f_idx in racket_data:
                ball_center, ball_bbox, ball_conf = ball_data[f_idx]
                racket_center, racket_bbox, racket_conf = racket_data[f_idx]
                
                # 计算球和拍的距离
                center_dist = euclidean_distance(ball_center, racket_center)
                
                # 检查球是否在球拍边界框内或非常接近
                ball_in_racket = (ball_bbox[0] >= racket_bbox[0] and 
                                ball_bbox[2] <= racket_bbox[2] and
                                ball_bbox[1] >= racket_bbox[1] and
                                ball_bbox[3] <= racket_bbox[3])
                
                # 计算IoU
                iou = bbox_iou(ball_bbox, racket_bbox)
                
                # ===== 修改评分逻辑 =====
                # 根据新需求，我们需要找到球和拍最靠近但尚未接触或重合的帧
                
                # 检查该帧是否有多个球的检测
                multi_ball_penalty = 0.0
                current_frame_detections = tracked[f_idx] if f_idx < len(tracked) else []
                ball_count = sum(1 for det in current_frame_detections if "ball" in det["label"].lower())
                if ball_count > 1:
                    # 如果检测到多个球，严重降低该帧的得分
                    multi_ball_penalty = 0.9  # 90%的惩罚
                    print(f"  帧 {f_idx} 检测到 {ball_count} 个球，应用多球惩罚")
                
                # 1. 基础距离评分 - 距离越小评分越高，但有一个最小阈值以避免选择重合的
                distance_score = 1.0 / (center_dist + 0.001)
                
                # 2. 重合或球在拍内的惩罚
                overlap_penalty = 0.0
                if ball_in_racket:  # 如果球在拍内，这是严重的重合，直接大幅度降低分数
                    overlap_penalty = 0.95  # 95%的惩罚，基本排除这些帧
                elif iou > 0.01:  # 非常严格的IoU阈值，几乎不允许任何重合
                    # 指数惩罚，IoU越大惩罚越大
                    overlap_penalty = min(0.9, iou * 10.0)  # 最大90%的惩罚
                
                # 综合所有惩罚因素
                total_penalty = max(overlap_penalty, multi_ball_penalty)
                
                # 如果有较明显的重合或多球，直接放低得分
                if total_penalty > 0.5:
                    contact_score = distance_score * 0.1  # 只保留原始分数的10%
                else:
                    # 3. 重新计算基本接触得分 - 优先选择接近但不重合的单球帧
                    contact_score = distance_score * (1.0 - total_penalty)
                
                # 额外奖励：距离合适且无重合的帧
                # 找到一个合理的接近距离阈值
                optimal_distance = 0.05  # 调整这个值以适应不同的场景
                if center_dist < optimal_distance * 2.0 and overlap_penalty < 0.1:
                    # 距离适中且几乎无重合，这是我们想要的
                    proximity_bonus = 2.0 * (1.0 - (center_dist / (optimal_distance * 2.0)))
                    contact_score += proximity_bonus
                
                # 考虑置信度
                confidence_factor = ball_conf * racket_conf
                contact_score *= confidence_factor
                
                # 考虑速度变化 - 保持不变，因为速度变化通常是接触前的指标
                velocity_change_factor = 0.0
                for vc_idx, vc_score in velocity_changes:
                    # 如果当前帧接近速度变化显著的帧，增加得分
                    if abs(f_idx - vc_idx) <= 2:  # 允许2帧的误差
                        velocity_change_factor = max(velocity_change_factor, vc_score)
                
                # 添加：检查前后是否有网球（连续性检查）
                continuity_factor = 0.0
                nearby_frames_with_ball = 0
                for offset in range(-3, 4):  # 检查前后3帧
                    if offset == 0:
                        continue
                    check_idx = f_idx + offset
                    if 0 <= check_idx < len(frames_list) and check_idx in ball_data:
                        nearby_frames_with_ball += 1
                        if abs(offset) == 1:  # 相邻帧权重更高
                            continuity_factor += 0.3
                        else:
                            continuity_factor += 0.1
                
                # 调整接触得分，考虑连续性和速度变化
                final_score = contact_score * (1.0 + velocity_change_factor) * (1.0 + continuity_factor)
                
                # 增加描述性信息
                contact_info = {
                    "frame_idx": f_idx,
                    "distance": center_dist,
                    "ball_in_racket": ball_in_racket,
                    "iou": iou,
                    "distance_score": distance_score,
                    "overlap_penalty": overlap_penalty,
                    "velocity_change": velocity_change_factor,
                    "continuity": continuity_factor,
                    "confidence": confidence_factor,
                    "final_score": final_score,
                    "nearby_frames": nearby_frames_with_ball
                }
                
                contact_frame_candidates.append((f_idx, final_score, nearby_frames_with_ball, contact_info))
                
                if final_score > 4.0:  # 降低打印阈值
                    significant_candidates.append((f_idx, final_score, nearby_frames_with_ball, contact_info))
                    print(f"  帧 {f_idx}: 距离={center_dist:.4f}, 球在拍内={ball_in_racket}, IoU={iou:.4f}, 重合惩罚={overlap_penalty:.2f}, "
                          f"距离评分={distance_score:.2f}, 置信度={confidence_factor:.2f}, 速度变化={velocity_change_factor:.2f}, "
                          f"连续性={continuity_factor:.2f}, 附近帧数={nearby_frames_with_ball}, 最终得分={final_score:.2f}")
        
        # 如果找不到候选帧，返回None
        if not contact_frame_candidates:
            print("\n未找到有效的接触帧候选")
            return None, 0, 0
        
        # 按照得分和连续性排序
        contact_frame_candidates.sort(key=lambda x: (x[2] >= 4, x[1]), reverse=True)
        
        # 筛选前5个候选项详细分析
        if len(contact_frame_candidates) >= 5:
            print("\n  排名前5的候选接触帧分析:")
            for i, (f_idx, score, _, info) in enumerate(contact_frame_candidates[:5]):
                print(f"  [{i+1}] 帧 {f_idx}: 得分={score:.2f}, 距离={info['distance']:.4f}, "
                      f"IoU={info['iou']:.4f}, 球在拍内={info['ball_in_racket']}, "
                      f"重合惩罚={info['overlap_penalty']:.2f}")
        
        # 选择得分最高的帧作为接触帧
        best_frame, best_score, nearby_count, _ = contact_frame_candidates[0]
        
        print(f"\n  选择帧 {best_frame} 作为最佳接触帧，得分: {best_score:.2f}")
        
        return best_frame, best_score, nearby_count
    
    # 使用函数选择最佳接触帧
    best_contact_result = find_best_contact_frame(frames_list, ball_data, racket_data, velocity_changes)
    
    # 检查是否找到有效的接触帧
    if best_contact_result[0] is None:
        print("\n未找到有效的接触帧候选，无法继续处理")
        return {
            "preparation_frame": "",
            "contact_frame": "",
            "follow_frame": "",
            "stroke_video": "",
            "output_directory": output_dir
        }
    
    # 提取返回结果
    best_contact_frame, best_score, nearby_count = best_contact_result
    
    print(f"\n步骤9: 确定最佳接触帧...")
    print(f"  选择帧 {best_contact_frame} 作为接触帧，得分: {best_score:.2f}")
    
    if significant_candidates:
        print("  得分较高的候选帧:")
        for f_idx, score, _ in sorted(significant_candidates, key=lambda x: (x[2] >= 4, x[1]), reverse=True)[:5]:
            print(f"    帧 {f_idx}: 得分={score:.2f}")

    #########################################
    # 10. 动态选择准备和跟随帧
    #########################################
    print("\n步骤10: 分析球的速度确定预备和跟随帧范围...")
    # 分析球的速度变化确定更合适的帧范围
    ball_positions_list = sorted([(f, c) for f, (c, _, _) in ball_data.items()])
    
    # 计算前后速度以找到最佳准备和跟随帧
    ball_speeds = []
    for i in range(1, len(ball_positions_list)):
        prev_idx, prev_center = ball_positions_list[i-1]
        curr_idx, curr_center = ball_positions_list[i]
        speed = euclidean_distance(prev_center, curr_center) / max(1, curr_idx - prev_idx)
        ball_speeds.append((prev_idx, curr_idx, speed))
    
    # 确定合适的预备和跟随帧范围
    prep_start_idx = max(0, best_contact_frame - 45)  # 默认预备范围
    follow_end_idx = min(len(frames_list) - 1, best_contact_frame + 45)  # 默认跟随范围
    
    # 尝试在速度变化显著的地方找到更好的边界
    if ball_speeds:
        for prev_idx, curr_idx, speed in ball_speeds:
            if curr_idx < best_contact_frame and speed > 0.01:  # 检测开始加速
                prep_start_idx = max(0, prev_idx - 10)
                print(f"  检测到开始加速点: 帧 {curr_idx}，速度={speed:.4f}")
            if prev_idx > best_contact_frame and speed > 0.01:  # 检测结束减速
                follow_end_idx = min(len(frames_list) - 1, curr_idx + 10)
                print(f"  检测到跟随减速点: 帧 {prev_idx}，速度={speed:.4f}")
    
    # 定义函数：选择准备击球的最佳帧（球拍速度最小）
    def find_prep_frame(best_contact_frame, racket_data, prep_start_idx):
        """
        选择准备击球动作时的帧，选择逻辑：
        在best_contact_frame前，选择最靠近best_contact_frame，且球拍速度最小的帧
        
        参数:
        best_contact_frame: 确定的接触帧索引
        racket_data: 球拍数据字典 {frame_idx: (center, bbox, conf)}
        prep_start_idx: 准备阶段的起始帧索引
        
        返回:
        最佳准备帧的索引
        """
        candidates = {}  # 存储候选帧及其球拍速度
        
        # 获取接触帧范围内的所有球拍帧
        prep_frames = [f for f in racket_data.keys() 
                       if prep_start_idx <= f < best_contact_frame]
        
        if not prep_frames:
            # 如果没有合适的候选帧，返回默认值
            return max(0, best_contact_frame - 30)
            
        print(f"  分析 {len(prep_frames)} 个准备阶段的球拍帧")
        
        # 计算每一帧的球拍速度
        for i in range(1, len(prep_frames)):
            curr_idx = prep_frames[i]
            prev_idx = prep_frames[i-1]
            
            # 如果帧间隔太大，跳过
            if curr_idx - prev_idx > 5:
                continue
                
            # 获取中心点
            prev_center, _, _ = racket_data[prev_idx]
            curr_center, _, _ = racket_data[curr_idx]
            
            # 计算速度 (归一化坐标的位移除以帧数)
            velocity = euclidean_distance(prev_center, curr_center) / (curr_idx - prev_idx)
            
            # 记录当前帧的速度
            candidates[curr_idx] = velocity
            
        if not candidates:
            # 如果没有速度数据，使用最靠近接触帧的准备帧
            closest_frame = max(prep_frames)
            print(f"  没有有效的球拍速度数据，选择最靠近接触帧的准备帧: {closest_frame}")
            return closest_frame
            
        # 打印候选帧的速度
        print("  准备阶段球拍速度:")
        for idx, speed in sorted(candidates.items()):
            print(f"    帧 {idx}: 速度={speed:.6f}")
        
        # 选择速度最小的帧，如果有多个相近的最小速度，选择最靠近接触帧的
        # 首先按照速度升序排序
        sorted_candidates = sorted(candidates.items(), key=lambda x: x[1])
        
        # 找到速度最小的阈值（最小速度的1.2倍内）
        min_speed = sorted_candidates[0][1]
        speed_threshold = min_speed * 1.2
        
        # 在阈值范围内，选择最靠近接触帧的
        closest_slow_frames = [idx for idx, speed in sorted_candidates 
                              if speed <= speed_threshold]
        
        if closest_slow_frames:
            best_prep_frame = max(closest_slow_frames)  # 最靠近接触帧的慢速帧
            print(f"  选择帧 {best_prep_frame} 作为最佳准备帧，速度={candidates[best_prep_frame]:.6f}")
            return best_prep_frame
        else:
            # 默认返回
            return max(0, best_contact_frame - 30)
    
    # 定义函数：选择完成击球后的最佳帧（球拍位置最高）
    def find_follow_frame(best_contact_frame, racket_data, follow_end_idx):
        """
        选择完成击球动作后的帧，选择逻辑：
        在best_contact_frame后，选择最靠近best_contact_frame，且球拍位置最高的帧
        
        参数:
        best_contact_frame: 确定的接触帧索引
        racket_data: 球拍数据字典 {frame_idx: (center, bbox, conf)}
        follow_end_idx: 跟随阶段的结束帧索引
        
        返回:
        最佳跟随帧的索引
        """
        candidates = {}  # 存储候选帧及其球拍高度位置 (y坐标越小位置越高)
        
        # 获取接触帧后的球拍帧
        follow_frames = [f for f in racket_data.keys() 
                         if best_contact_frame < f <= follow_end_idx]
        
        if not follow_frames:
            # 如果没有合适的候选帧，返回默认值
            return min(len(frames_list) - 1, best_contact_frame + 30)
            
        print(f"  分析 {len(follow_frames)} 个跟随阶段的球拍帧")
        
        # 记录每一帧的球拍位置高度 (y坐标)
        for idx in follow_frames:
            center, _, _ = racket_data[idx]
            # y坐标越小，位置越高 (图像坐标系中y轴向下)
            y_position = center[1]
            candidates[idx] = y_position
            
        if not candidates:
            # 如果没有位置数据，使用最靠近接触帧的跟随帧
            closest_frame = min(follow_frames)
            print(f"  没有有效的球拍位置数据，选择最靠近接触帧的跟随帧: {closest_frame}")
            return closest_frame
            
        # 打印候选帧的高度位置
        print("  跟随阶段球拍高度位置:")
        for idx, y_pos in sorted(candidates.items()):
            print(f"    帧 {idx}: y坐标={y_pos:.4f} (越小越高)")
        
        # 选择位置最高的帧 (y坐标最小)
        # 首先按照y坐标升序排序 (越小越高)
        sorted_candidates = sorted(candidates.items(), key=lambda x: x[1])
        
        # 找到位置最高的阈值（最高位置的1.1倍内）
        min_y = sorted_candidates[0][1]
        height_threshold = min_y * 1.1
        
        # 在阈值范围内，选择最靠近接触帧的
        closest_high_frames = [idx for idx, y_pos in sorted_candidates 
                              if y_pos <= height_threshold]
        
        if closest_high_frames:
            best_follow_frame = min(closest_high_frames)  # 最靠近接触帧的高位置帧
            print(f"  选择帧 {best_follow_frame} 作为最佳跟随帧，y坐标={candidates[best_follow_frame]:.4f}")
            return best_follow_frame
        else:
            # 默认返回
            return min(len(frames_list) - 1, best_contact_frame + 30)
    
    # 使用新函数选择最佳准备帧和跟随帧
    prep_frame_idx = find_prep_frame(best_contact_frame, racket_data, prep_start_idx)
    follow_frame_idx = find_follow_frame(best_contact_frame, racket_data, follow_end_idx)
    
    print(f"  预备范围: 帧 {prep_start_idx} 到 {best_contact_frame}")
    print(f"  跟随范围: 帧 {best_contact_frame} 到 {follow_end_idx}")
    print(f"  选择的关键帧: 预备={prep_frame_idx}, 接触={best_contact_frame}, 跟随={follow_frame_idx}")

    prep_frame = frames_list[prep_frame_idx]
    contact_frame = frames_list[best_contact_frame]
    follow_frame = frames_list[follow_frame_idx]

    #########################################
    # 11. 保存关键帧和视频
    #########################################
    print("\n步骤11: 保存关键帧和视频...")
    
    # 添加可视化标记
    prep_vis = overlay_racket_ball(prep_frame_idx, prep_frame)
    contact_vis = overlay_racket_ball(best_contact_frame, contact_frame)
    follow_vis = overlay_racket_ball(follow_frame_idx, follow_frame)

    from uuid import uuid4
    prep_path = os.path.join(output_dir, f"prep.jpg")
    contact_path = os.path.join(output_dir, f"contact.jpg")
    follow_path = os.path.join(output_dir, f"follow.jpg")

    # 保存图像
    save_image(prep_vis, prep_path)
    save_image(contact_vis, contact_path)
    save_image(follow_vis, follow_path)
    print(f"  保存了3个关键帧图像: {prep_path}, {contact_path}, {follow_path}")

    # 保存视频
    clip_frames = frames_list[prep_start_idx:follow_end_idx + 1]
    
    # 创建帧标记文件
    ball_frames_info = os.path.join(output_dir, "ball_frames.txt")
    with open(ball_frames_info, "w") as f:
        f.write("网球检测信息摘要\n")
        f.write(f"共有 {len(frames_with_ball)} 帧直接检测到网球\n")
        f.write(f"共有 {len(ball_data)} 帧追踪和插值后有网球\n\n")
        
        f.write("直接检测到网球的帧：\n")
        for frame_idx in sorted(frames_with_ball):
            f.write(f"帧 {frame_idx}\n")
            
        f.write("\n追踪和插值后的所有网球帧：\n")
        for frame_idx in sorted(ball_data.keys()):
            _, _, conf = ball_data[frame_idx]
            f.write(f"帧 {frame_idx} (置信度: {conf:.3f})\n")
    
    print(f"  保存了网球帧信息到: {ball_frames_info}")
    
    # 在每一帧上叠加边界框
    enhanced_clip_frames = []
    for i, frame in enumerate(clip_frames):
        actual_idx = prep_start_idx + i
        
        # 在边框位置添加帧号标记
        frame_with_idx = frame.copy()
        h, w = frame.shape[:2]
        frame_text = f"Frame: {actual_idx}"
        cv2.putText(frame_with_idx, frame_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        # 如果此帧有检测到网球或球拍，添加可视化
        if actual_idx < len(tracked) and (actual_idx in ball_data or actual_idx in racket_data):
            enhanced_frame = overlay_racket_ball(actual_idx, frame_with_idx)
        else:
            enhanced_frame = frame_with_idx
            
        enhanced_clip_frames.append(enhanced_frame)
        
        # 保存增强后的每一帧
        enhanced_frame_path = os.path.join(frames_dir, f"enhanced_frame_{i:03d}.jpg")
        save_image(enhanced_frame, enhanced_frame_path)
    
    # 使用增强后的帧序列保存视频
    stroke_video_path = os.path.join(output_dir, "stroke_video.mp4")
    save_video(enhanced_clip_frames, stroke_video_path, fps=15)  # 增加帧率获得更流畅的效果
    print(f"  保存了击球视频片段: {stroke_video_path}，包含 {len(enhanced_clip_frames)} 帧")

    # 创建一个结果摘要文件
    summary_path = os.path.join(output_dir, "summary.txt")
    with open(summary_path, "w") as f:
        f.write(f"处理视频: {video_path}\n")
        f.write(f"总帧数: {len(frames_list)}\n")
        f.write(f"检测到的网球实例: {ball_detection_count}\n")
        f.write(f"检测到的球拍实例: {racket_detection_count}\n")
        f.write(f"最佳接触帧: {best_contact_frame} (得分: {best_score:.2f})\n")
        f.write(f"预备帧: {prep_frame_idx}\n")
        f.write(f"跟随帧: {follow_frame_idx}\n")
        if ball_velocities:
            f.write(f"网球平均速度: {sum(v[3] for v in ball_velocities) / len(ball_velocities):.6f}\n")
            f.write(f"网球最大速度: {max(v[3] for v in ball_velocities):.6f}\n")
    
    print(f"  保存了结果摘要: {summary_path}")
    print("===== 处理完成 =====")
    
    #########################################
    # 12. 返回结果
    #########################################
    # 返回结果字典
    return {
        "preparation_frame": prep_path,
        "contact_frame": contact_path,
        "follow_frame": follow_path,
        "stroke_video": stroke_video_path,
        "output_directory": output_dir
    }
