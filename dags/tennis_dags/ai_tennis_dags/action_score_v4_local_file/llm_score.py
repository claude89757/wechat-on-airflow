# 标准库导入
import os
from openai import OpenAI
import base64

from tennis_dags.ai_tennis_dags.action_score_v4_local_file.vision_agent_fuction_by_api import process_tennis_video

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import re
from airflow.models import Variable


def get_tennis_action_comment(action_image_path: str, model_name: str = "qwen-vl-max-latest", action_type: str = "击球动作") -> str:
    """
    通过阿里云的AI模型，获取网球动作的评论
    """
    if action_type == "引拍动作":
        action_standard = """
        **引拍动作的识别标准**：
        - 不要求引拍动作必须完美标准
        - 允许各种准备击球的拍子举起姿态

        **引拍动作的评分标准**：
        - 重心转移：身体重心是否自然向后转移
        - 拍头路线：拍面是否拉开到位，形成合适的引拍弧线
        - 手腕固定：手腕是否保持稳定不松散
        - 肩部旋转：肩膀是否充分转动带动上半身
        - 握拍姿势：是否使用适合该击球的标准握法
        """ 
        specific_focus = "重点关注是否有举拍准备动作，识别标准可适当放宽"
        common_issues = "常见问题：引拍幅度、手腕稳定性"
    elif action_type == "击球动作":
        action_standard = """
        **击球动作的识别标准**：
        - 不要求动作必须完美标准
        - 允许各种击球姿态（正手、反手、截击等）

        **击球动作的评分标准**：
        - 击球点：是否在合理区域内完成击球（允许一定偏差）
        - 拍面控制：击球时拍面方向是否基本正确
        - 腿部支撑：下肢是否提供基本的稳定支撑
        - 力量传递：身体是否有基本的协调发力
        - 视线跟踪：是否大致朝向球的方向
        """
        specific_focus = "重点关注是否有网球拍击球场景，标准可适当放宽"
        common_issues = "常见问题：击球时机把握、拍面稳定性"
    elif action_type == "随挥动作":
        action_standard = """
        **随挥动作的识别标准**：
        - 不要求随挥动作必须完美标准
        - 允许各种持拍姿态和动作阶段

        **随挥动作的评分标准**：
        - 动作完整性：是否完成充分的随挥跟随动作
        - 平衡保持：击球后身体是否保持平衡
        - 重心转移：重心是否自然向前转移
        - 收拍流畅度：是否平稳自然地完成收拍
        - 恢复能力：是否迅速恢复到击球后的准备姿态
        """
        specific_focus = "重点关注是否有网球拍出现，识别标准极度放宽"
        common_issues = "常见问题：随挥完整性、收拍稳定性"
    else:
        raise ValueError(f"不支持的动作类型: {action_type}")

    system_prompt = f"""# Role and Objective
你是专业网球教练，负责快速准确评估运动员的{action_type}。

# Instructions
观察图片中的网球运动员，重点识别当前动作是否为{action_type}。

## 动作识别要点
{action_type}的关键特征：
{action_standard}

## 评估重点
{specific_focus}

## 常见问题
{common_issues}

# Reasoning Steps
请按以下步骤进行系统分析：

1. **动作识别**：首先判断图片中是否有网球运动员和网球拍
2. **动作分类**：确认当前动作是否符合{action_type}的特征
3. **技术要点检查**：逐项对照技术标准进行评估
4. **常见问题识别**：检查是否存在该动作类型的常见问题
5. **等级判定**：基于技术表现综合评定等级
6. **建议制定**：针对发现的问题给出最关键的改进建议

# Output Format - 必须严格遵守
**重要：必须严格按照以下格式输出，不得添加任何其他内容！**

```
评分等级：[S/A/B/C/无效]
动作评价：[6-8字简明评价]
动作建议：[6-8字关键建议]
```

## 格式要求：
- 只输出上述三行内容，不得添加其他文字
- 每行必须以指定的标签开头
- 评价和建议严格控制在6-8个字
- 不要添加括号、引号或其他符号
- 不要添加详细解释或分析

# Examples

## 有效动作示例
```
评分等级：A
动作评价：技术规范到位
动作建议：保持稳定发挥
```

## 无效图片示例
```
评分等级：无效
动作评价：非{action_type}或无法识别
动作建议：提供清晰动作图片
```

## 错误格式示例（禁止使用）
❌ 错误：添加额外内容
```
评分等级：A
动作评价：技术规范到位，整体表现优秀
动作建议：保持稳定发挥，继续练习
详细分析：运动员的姿态很标准...
```

✅ 正确：严格按格式
```
评分等级：A
动作评价：技术规范到位
动作建议：保持稳定发挥
```

# Context
- 当前目标：评估{action_type}
- 要求：输出简洁、评估准确、格式标准
- 重点：{specific_focus}
- 注意：{common_issues}

# Final Instructions
**格式要求再次强调：**
1. 只输出三行指定内容
2. 严格按照"标签：内容"格式
3. 内容简洁，6-8字限制
4. 不要添加任何解释、分析或其他文字

请快速识别图片中的动作类型，如果确认是{action_type}则进行评分，否则标记为无效。

开始分析："""

    print(f"system_prompt: \n{system_prompt}")
    
    #  base 64 编码格式
    def encode_image(image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    # 将xxxx/test.png替换为你本地图像的绝对路径
    base64_image = encode_image(action_image_path)
    client = OpenAI(
        # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
        api_key=Variable.get('DASHSCOPE_API_KEY'),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    # 获取动作评价  
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": [{"type":"text","text": system_prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        # 需要注意，传入Base64，图像格式（即image/{format}）需要与支持的图片列表中的Content Type保持一致。"f"是字符串格式化的方法。
                        # PNG图像：  f"data:image/png;base64,{base64_image}"
                        # JPEG图像： f"data:image/jpeg;base64,{base64_image}"
                        # WEBP图像： f"data:image/webp;base64,{base64_image}"
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}, 
                    },
                ],
            }
        ],
    )
    return completion.choices[0].message.content

# 三张动作图片+得分合并到一张长图
def extract_score_from_comment(comment_text):
    """从评论文本中提取分数等级和具体评价"""
    score_level = re.search(r'评分等级：([SABC])', comment_text)
    score_level = score_level.group(1) if score_level else "C"
    
    # 提取各项评价
    evaluations = []
    for line in comment_text.split('\n'):
        if "：" in line and "评分等级" not in line:
            key, value = line.split("：", 1)
            evaluations.append((key, value))
    
    return score_level, evaluations

def create_score_image(width, height, level, color):
    """创建一个带有等级的圆形图像"""
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # 画圆
    draw.ellipse((0, 0, width, height), fill=color)
    
    # 添加等级文字
    font_size = height // 2
    
    # 优先尝试使用已安装的字体
    font_paths = [
        # 已安装的字体包
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",  # Noto CJK 字体
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",         # 文泉驿正黑
        # 备用字体路径
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    
    # 尝试加载字体
    font = None
    for font_path in font_paths:
        try:
            font = ImageFont.truetype(font_path, font_size)
            break
        except Exception:
            continue
    
    # 如果仍然无法加载字体，使用默认字体
    if font is None:
        font = ImageFont.load_default()
        text = level  # 只显示字母S/A/B/C，不显示"级"字
    else:
        text = level
    
    # 计算文本位置并绘制
    # 使用textbbox获取文本边界框
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width = right - left
    text_height = bottom - top
    
    # 计算居中位置 - 确保文本真正居中
    position_x = (width - text_width) // 2 - left  # 减去left偏移以修正位置
    position_y = (height - text_height) // 2 - top  # 减去top偏移以修正位置
    
    draw.text((position_x, position_y), text, fill="white", font=font)
    
    return img

def merge_images_with_scores(preparation_image, preparation_score, 
                            contact_image, contact_score,
                            follow_image, follow_score,
                            output_path="/tmp/tennis_analysis.jpg"):
    """合并三张图片和评分为一张长图"""
    # 打开三张图片
    prep_img = Image.open(preparation_image)
    contact_img = Image.open(contact_image)
    follow_img = Image.open(follow_image)
    
    # 调整所有图片为相同宽度
    width = 900  # 增加宽度以适应更多内容
    height = int(width * prep_img.height / prep_img.width)
    
    prep_img = prep_img.resize((width, height))
    contact_img = contact_img.resize((width, height))
    follow_img = follow_img.resize((width, height))
    
    # 解析评分
    prep_level, prep_eval = extract_score_from_comment(preparation_score)
    contact_level, contact_eval = extract_score_from_comment(contact_score)
    follow_level, follow_eval = extract_score_from_comment(follow_score)
    
    # 设置颜色(S和A用绿色，B和C用橙色)
    level_colors = {
        "S": (0, 180, 0),  # 深绿色
        "A": (34, 139, 34),  # 森林绿
        "B": (255, 140, 0),  # 深橙色
        "C": (255, 69, 0)   # 红橙色
    }
    
    prep_color = level_colors.get(prep_level, (255, 128, 0))
    contact_color = level_colors.get(contact_level, (255, 128, 0))
    follow_color = level_colors.get(follow_level, (255, 128, 0))
    
    # 创建分数图标
    score_size = 120
    prep_score_img = create_score_image(score_size, score_size, prep_level, prep_color)
    contact_score_img = create_score_image(score_size, score_size, contact_level, contact_color)
    follow_score_img = create_score_image(score_size, score_size, follow_level, follow_color)
    
    # 设置每个部分的标题
    titles = ["【引拍动作】", "【击球动作】", "【随挥动作】"]
    
    # 加载字体
    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    
    title_font = None
    eval_font = None
    
    for font_path in font_paths:
        try:
            title_font = ImageFont.truetype(font_path, 40)
            eval_font = ImageFont.truetype(font_path, 28)
            break
        except Exception:
            continue
    
    if title_font is None or eval_font is None:
        title_font = ImageFont.load_default()
        eval_font = ImageFont.load_default()
        print("警告：未能加载中文字体，将使用默认字体")
        titles = ["[Preparation]", "[Start]", "[Hitting]"]
    
    # 计算各部分的高度
    # 每个评价项目的高度
    item_height = 45
    # 计算每个部分评价区域所需的高度
    eval_height_prep = (len(prep_eval) * item_height) + 50  # 增加底部边距
    eval_height_contact = (len(contact_eval) * item_height) + 50
    eval_height_follow = (len(follow_eval) * item_height) + 50
    
    # 最大评价区域高度
    max_eval_height = max(eval_height_prep, eval_height_contact, eval_height_follow)
    
    # 每个部分的高度 = 标题(60) + 间距(20) + 图片高度 + 间距(30) + 评价区域高度 + 部分间距(60)
    title_height = 60
    title_margin = 20
    img_eval_margin = 30
    section_margin = 60
    
    section_height = title_height + title_margin + height + img_eval_margin + max_eval_height + section_margin
    
    # 创建最终图像 - 增加高度以确保足够空间
    final_height = section_height * 3 + 50  # 底部增加一些边距
    final_image = Image.new("RGB", (width, final_height), (255, 255, 255))
    draw = ImageDraw.Draw(final_image)
    
    # 计算左边距和评价文本起始位置
    left_margin = 30
    text_start_x = score_size + left_margin + 30
    
    # 绘制三个部分
    for i in range(3):
        # 计算当前部分的起始位置
        y_offset = i * section_height
        
        # 绘制标题
        title_width = draw.textbbox((0, 0), titles[i], font=title_font)[2]
        title_x = (width - title_width) // 2  # 居中
        draw.text((title_x, y_offset + 30), titles[i], fill=(0, 0, 0), font=title_font)
        
        # 确定图片位置
        img_y = y_offset + title_height + title_margin
        
        # 选择当前部分的图片和评分
        if i == 0:
            img = prep_img
            score_img = prep_score_img
            evaluations = prep_eval
        elif i == 1:
            img = contact_img
            score_img = contact_score_img
            evaluations = contact_eval
        else:
            img = follow_img
            score_img = follow_score_img
            evaluations = follow_eval
        
        # 粘贴图片
        final_image.paste(img, (0, img_y))
        
        # 计算评价区域顶部y坐标
        eval_section_top = img_y + height + img_eval_margin
        
        # 粘贴分数图标
        final_image.paste(score_img, (left_margin, eval_section_top), score_img)
        
        # 绘制评价文本
        eval_y = eval_section_top + 10
        for item, value in evaluations:
            text = f"【{item}】 {value}"
            draw.text((text_start_x, eval_y), text, fill=(0, 0, 0), font=eval_font)
            eval_y += item_height
    
    # 保存最终图像
    final_image.save(output_path)
    
    return output_path


def get_tennis_action_score(video_path: str, output_dir: str):
    """
    获取网球动作得分
    """
    print(f"video_path: {video_path}")
    print(f"output_dir: {output_dir}")
    result = process_tennis_video(video_path, output_dir)
    print(f"result: {result}")

    preparation_image = result["preparation_frame"]
    contact_image = result["contact_frame"]
    follow_image = result["follow_frame"]
    
    score_result_list = []

    # 获取准备动作得分
    preparation_score = get_tennis_action_comment(preparation_image, action_type="引拍动作")
    print(f"preparation_score: {preparation_score}")
    score_result_list.append(f"## 引拍动作: \n{preparation_score}")

    # 获取击球动作得分
    contact_score = get_tennis_action_comment(contact_image, action_type="击球动作")
    print(f"contact_score: {contact_score}")
    score_result_list.append(f"## 击球动作: \n{contact_score}")

    # 获取跟随动作得分
    follow_score = get_tennis_action_comment(follow_image, action_type="随挥动作")
    print(f"follow_score: {follow_score}")
    score_result_list.append(f"## 随挥动作: \n{follow_score}")

    # 将评分结果列表转换为字符串
    score_result_text = "\n\n".join(score_result_list)

    # 合并三张图片和评分
    output_image = merge_images_with_scores(
        preparation_image, preparation_score,
        contact_image, contact_score,
        follow_image, follow_score,
        output_path=f"{output_dir}/tennis_analysis_{os.path.basename(video_path).split('.')[0]}.jpg"
    )
    
    # 将合并后的图片路径添加到结果中
    result["analysis_image"] = output_image

    print(f"result: {result}")
    print(f"score_result_text: {score_result_text}")
    return result, score_result_text
