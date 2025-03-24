# 标准库导入
import os
from openai import OpenAI
import base64

from ai_tennis_dags.action_score_v2.vision_agent_fuction import process_tennis_video

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import re
from airflow.models import Variable


def get_tennis_action_comment(action_image_path: str, model_name: str = "qwen-vl-max-latest", action_type: str = "击球准备动作") -> str:
    """
    通过阿里云的AI模型，获取网球动作的评论
    """
    system_prompt = f"专业的网球教练，擅长对网球动作进行分析和评价。请结合照片网球运动员的{action_type}的细节，给出评价。格式如下：\n" \
                    f"评分等级：S|A|B|C\n" \
                    f"动作评价：10字以内\n" \
                    f"动作建议：10字以内(如果比较完美，可以不给出建议)"

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
        text = f"{level}级"
    
    # 计算文本位置并绘制
    text_width, text_height = draw.textbbox((0, 0), text, font=font)[2:]
    position = ((width - text_width) // 2, (height - text_height) // 2)
    draw.text(position, text, fill="white", font=font)
    
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
    
    # 创建分数图标 - 减小尺寸
    score_size = 120  # 从150减小到120
    prep_score_img = create_score_image(score_size, score_size, prep_level, prep_color)
    contact_score_img = create_score_image(score_size, score_size, contact_level, contact_color)
    follow_score_img = create_score_image(score_size, score_size, follow_level, follow_color)
    
    # 设置每个部分的标题
    titles = ["【引拍准备】", "【发力启动】", "【挥拍击球】"]
    
    # 设置每个部分的高度（图片+评分+评价）
    # 减小评价区域的高度，减少行间距
    eval_height_prep = len(prep_eval) * 45 + 40  # 每个评价45高度(从60减小)，顶部留40的空间(从50减小)
    eval_height_contact = len(contact_eval) * 45 + 40
    eval_height_follow = len(follow_eval) * 45 + 40
    
    # 找出最大的评价区域高度
    max_eval_height = max(eval_height_prep, eval_height_contact, eval_height_follow)
    
    # 每个部分的高度 = 图片高度 + 评价区域高度
    section_height = height + max_eval_height
    
    # 创建最终图像
    final_height = section_height * 3 + 100  # 底部增加一些边距
    final_image = Image.new("RGB", (width, final_height), (255, 255, 255))
    
    # 优先尝试使用已安装的字体
    font_paths = [
        # 已安装的字体包
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",  # Noto CJK 字体
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",         # 文泉驿正黑
        # 备用字体路径
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    
    # 尝试加载字体 - 减小字体大小
    title_font = None
    eval_font = None
    
    for font_path in font_paths:
        try:
            title_font = ImageFont.truetype(font_path, 40)  # 从50减小到40
            eval_font = ImageFont.truetype(font_path, 28)   # 从36减小到28
            break
        except Exception:
            continue
    
    # 如果仍然无法加载字体，使用默认字体
    if title_font is None or eval_font is None:
        title_font = ImageFont.load_default()
        eval_font = ImageFont.load_default()
        print("警告：未能加载中文字体，将使用默认字体")
        # 修改标题为英文
        titles = ["[Preparation]", "[Start]", "[Hitting]"]
    
    draw = ImageDraw.Draw(final_image)
    
    # 计算左边距和评价文本起始位置
    left_margin = 30  # 减小左边距从50到30
    text_start_x = score_size + left_margin + 30  # 减小额外间距从50到30
    
    # 绘制第一部分：准备动作
    y_offset = 30  # 减小顶部边距从50到30
    # 标题
    title_width = draw.textbbox((0, 0), titles[0], font=title_font)[2]
    title_x = (width - title_width) // 2  # 居中
    draw.text((title_x, y_offset), titles[0], fill=(0, 0, 0), font=title_font)
    
    # 图片 (位置y_offset + 60) - 减小间距从70到60
    final_image.paste(prep_img, (0, y_offset + 60))
    
    # 计算评价区域顶部y坐标
    eval_section_top = y_offset + 60 + height + 15  # 减小间距从20到15
    
    # 分数图标 (居左放置)
    final_image.paste(prep_score_img, (left_margin, eval_section_top), prep_score_img)
    
    # 评价 (评价文本右对齐，整齐排列)
    eval_y = eval_section_top + 10  # 减小间距从20到10
    for item, value in prep_eval:
        text = f"【{item}】 {value}"
        draw.text((text_start_x, eval_y), text, fill=(0, 0, 0), font=eval_font)
        eval_y += 45  # 减小行间距从60到45
    
    # 绘制第二部分：发力启动
    y_offset = section_height + 30  # 减小间距从50到30
    # 标题
    title_width = draw.textbbox((0, 0), titles[1], font=title_font)[2]
    title_x = (width - title_width) // 2  # 居中
    draw.text((title_x, y_offset), titles[1], fill=(0, 0, 0), font=title_font)
    
    # 图片
    final_image.paste(contact_img, (0, y_offset + 60))
    
    # 计算评价区域顶部y坐标
    eval_section_top = y_offset + 60 + height + 15
    
    # 分数图标
    final_image.paste(contact_score_img, (left_margin, eval_section_top), contact_score_img)
    
    # 评价
    eval_y = eval_section_top + 10
    for item, value in contact_eval:
        text = f"【{item}】 {value}"
        draw.text((text_start_x, eval_y), text, fill=(0, 0, 0), font=eval_font)
        eval_y += 45
    
    # 绘制第三部分：跟随动作
    y_offset = section_height * 2 + 30  # 减小间距从50到30
    # 标题
    title_width = draw.textbbox((0, 0), titles[2], font=title_font)[2]
    title_x = (width - title_width) // 2  # 居中
    draw.text((title_x, y_offset), titles[2], fill=(0, 0, 0), font=title_font)
    
    # 图片
    final_image.paste(follow_img, (0, y_offset + 60))
    
    # 计算评价区域顶部y坐标
    eval_section_top = y_offset + 60 + height + 15
    
    # 分数图标
    final_image.paste(follow_score_img, (left_margin, eval_section_top), follow_score_img)
    
    # 评价
    eval_y = eval_section_top + 10
    for item, value in follow_eval:
        text = f"【{item}】 {value}"
        draw.text((text_start_x, eval_y), text, fill=(0, 0, 0), font=eval_font)
        eval_y += 45
    
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

    # 获取准备动作得分
    preparation_score = get_tennis_action_comment(preparation_image, action_type="准备动作")
    print(f"preparation_score: {preparation_score}")

    # 获取击球动作得分
    contact_score = get_tennis_action_comment(contact_image, action_type="击球动作")
    print(f"contact_score: {contact_score}")

    # 获取跟随动作得分
    follow_score = get_tennis_action_comment(follow_image, action_type="跟随动作")
    print(f"follow_score: {follow_score}")
    
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
    return result
