"""
简单的算术验证码（加减法，两位数以内）
为什么用算术题而不是图形文字：
  1. 不用装任何图片库（Pillow/captcha 都不用），生成纯 SVG，零依赖
  2. 防机器人足够用（针对这个班级小系统的量级），又不会难用到人都认不出
  3. 答案是整数，校验简单

答案存在会话里（session["captcha_answer"]），未登录用户也有会话 Cookie，
所以不需要额外的 captcha_id / Redis。
"""

import random
from io import StringIO


def generate_captcha() -> tuple[str, int]:
    """生成一道算术题。返回 (SVG 字符串, 正确答案)"""

    a = random.randint(10, 99)
    b = random.randint(1, 99)
    # 加法占 2/3，减法占 1/3（减法保证结果为正）
    if random.random() < 0.66:
        op = "+"
        answer = a + b
    else:
        op = "-"
        if a < b:
            a, b = b, a
        answer = a - b

    text = f"{a} {op} {b} = ?"
    return _text_to_svg(text), answer


def _text_to_svg(text: str) -> str:
    """把算式文本渲染成一张带干扰线的 SVG 图片

    故意不用任何外部库：就是几个 <text> + 几条 <line>，
    颜色随机、角度微微倾斜，足够挡住脚本的简单 OCR。
    """
    # 画布尺寸
    w, h = 120, 40
    # 颜色：深灰到深蓝之间随机挑，避开太浅看不清的
    colors = ["#1f2d3d", "#2c3e50", "#3a5169", "#409EFF", "#303133", "#606266"]

    svg = StringIO()
    svg.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">')
    svg.write(f'<rect width="{w}" height="{h}" fill="#f5f7fa" rx="4"/>')

    # 干扰线：3 条，颜色随机，从左到右斜跨
    for _ in range(3):
        x1 = random.randint(0, w // 3)
        y1 = random.randint(0, h)
        x2 = random.randint(w * 2 // 3, w)
        y2 = random.randint(0, h)
        color = random.choice(colors)
        svg.write(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1" opacity="0.4"/>')

    # 数字每个字单独写，微微错开高度和角度，看起来更像"验证码"
    x = 10
    for ch in text:
        color = random.choice(colors)
        dy = random.randint(-3, 5)
        rotate = random.randint(-8, 8)
        font_size = random.randint(20, 26)
        svg.write(
            f'<text x="{x}" y="{h // 2 + dy + font_size // 3}" '
            f'fill="{color}" font-size="{font_size}" font-weight="bold" '
            f'font-family="monospace" transform="rotate({rotate} {x} {h // 2})">'
            f'{ch}</text>'
        )
        x += 14 if ch.isdigit() else 10

    svg.write('</svg>')
    return svg.getvalue()
