"""登录页的人机验证码：字符图（含语音）/ 拖动拼图

用哪种由 `config.captcha_mode()` 决定（后台「运维」或 `CAPTCHA_MODE` 配置）：

  * `captcha`（默认）— 用 **captcha** 库生成字符图，另提供同答案的语音版本
    （无障碍：看不清图的人可以听 4 位数字）。库自带字体和语音数据，镜像里
    不用再装 ttf；
  * `slider` — 用 Pillow 现场从背景上抠一张拼图（拖动对齐）；
  * `turnstile` — 交给 Cloudflare，本模块不参与。

三种方式的答案都只存在服务端会话里：

    {"kind": "chars" | "slide", "value": <文本 或 缺口横坐标>, "at": 时间戳}

校验后立刻清掉（换一张才能再试），并且都有 2 分钟有效期。
字符验证码统一用 **4 位数字**：音频语音包只覆盖数字，两边答案格式保持一致，
也顺带避免了 O/0、l/1 这类看不清的混淆。
"""

import base64
import random
import string
import time
from io import BytesIO

from captcha.audio import AudioCaptcha
from captcha.image import ImageCaptcha
from PIL import Image, ImageDraw, ImageEnhance

# ---------- 字符图 / 语音 ----------

CHARS_LENGTH = 4
# 只用数字：captcha 库的内置语音只有 0-9，统一字符集才能「图/语音」同一答案
CHARS_ALPHABET = string.digits
IMAGE_WIDTH = 160
IMAGE_HEIGHT = 60

# ---------- 拖动拼图 ----------

WIDTH = 320
HEIGHT = 160
PIECE = 52
PAD = 12
# 允许的横向误差（原图像素）。太小会让人对不准，太大给脚本留了太多尝试空间
TOLERANCE = 8

# 一张图/一段语音的有效期。拖完/听完就提交，正常几秒内完成
TTL_SECONDS = 120

# 缺口横向允许的范围：太靠左会和拼图块的初始位置重叠（看着已经对上了），
# 太靠右则没有拖动空间
_X_MIN = PIECE + 40
_X_MAX = WIDTH - PIECE - PAD - 12
_Y_MIN = 8
_Y_MAX = HEIGHT - PIECE - PAD - 8

# 字体/语音数据加载一次就够了：每个请求重建一遍纯属浪费
_image_captcha: ImageCaptcha | None = None
_audio_captcha: AudioCaptcha | None = None


def _chars() -> str:
    return "".join(random.choices(CHARS_ALPHABET, k=CHARS_LENGTH))


def _image_engine() -> ImageCaptcha:
    global _image_captcha
    if _image_captcha is None:
        _image_captcha = ImageCaptcha(width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
    return _image_captcha


def _audio_engine() -> AudioCaptcha:
    global _audio_captcha
    if _audio_captcha is None:
        _audio_captcha = AudioCaptcha()
    return _audio_captcha


def generate_chars_image() -> tuple[bytes, str]:
    """一张字符图。返回 (PNG 字节, 答案文本)"""
    text = _chars()
    buffer = _image_engine().generate(text, format="png")
    return buffer.getvalue(), text


def generate_chars_audio() -> tuple[bytes, str]:
    """同一套答案的语音版（无障碍）。返回 (WAV 字节, 答案文本)

    注意是**新生成一个答案**：声音和图片不能共用一个 session 槽位，
    否则先看图再点「听语音」时，图上的字和耳里的数字会对不上。
    前端切换成语音模式时会把图隐藏掉，以语音这条为准。
    """
    text = _chars()
    return bytes(_audio_engine().generate(text)), text


# ---------- 拖动拼图 ----------


def _rand_color(low: int = 70, high: int = 210) -> tuple[int, int, int]:
    return tuple(random.randint(low, high) for _ in range(3))  # type: ignore[return-value]


def _background() -> Image.Image:
    """随机渐变 + 光斑 + 噪点

    纯色背景的缺口一眼就能算出来（找那块颜色差），所以要把背景做「花」：
    渐变让左右两侧亮度不同，光斑把局部提亮，噪点打散像素级的纯色区域。
    """
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)

    left, right = _rand_color(), _rand_color()
    for x in range(WIDTH):
        ratio = x / (WIDTH - 1)
        color = tuple(
            int(a + (b - a) * ratio) for a, b in zip(left, right)
        )
        draw.line([(x, 0), (x, HEIGHT)], fill=color)

    # 光斑：半透明圆叠上去，半径和亮度都随机
    for _ in range(6):
        radius = random.randint(24, 72)
        cx = random.randint(0, WIDTH)
        cy = random.randint(0, HEIGHT)
        spot = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(spot).ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*_rand_color(120, 255), random.randint(25, 70)),
        )
        image = Image.alpha_composite(image.convert("RGBA"), spot).convert("RGB")

    # 噪点：几百个像素随机加减一点亮度
    pixels = image.load()
    for _ in range(WIDTH * HEIGHT // 30):
        x, y = random.randrange(WIDTH), random.randrange(HEIGHT)
        r, g, b = pixels[x, y]
        delta = random.randint(-22, 22)
        pixels[x, y] = (
            max(0, min(255, r + delta)),
            max(0, min(255, g + delta)),
            max(0, min(255, b + delta)),
        )
    return image


def _piece_mask() -> Image.Image:
    """拼图块的形状：圆角方片 + 右侧一个凸起圆头

    尺寸含 PAD 的留白，粘贴/裁剪都用同一张 mask，块的轮廓和缺口才严丝合缝。
    """
    mask = Image.new("L", (PIECE + PAD, PIECE + PAD), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, PIECE, PIECE], radius=8, fill=255)
    radius = 9
    draw.ellipse([PIECE - radius, PIECE // 2 - radius,
                  PIECE + radius, PIECE // 2 + radius], fill=255)
    return mask


def _data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def generate_slide() -> tuple[dict, int]:
    """生成一张拼图。返回 (给前端的图与尺寸, 缺口横坐标)

    返回值刻意不含答案：前端只知道「缺口在哪一行、块多大」，横向位置得自己拖。
    """
    background = _background()
    x = random.randint(_X_MIN, _X_MAX)
    y = random.randint(_Y_MIN, _Y_MAX)
    mask = _piece_mask()

    def crop(source: Image.Image) -> Image.Image:
        return source.crop((x, y, x + PIECE + PAD, y + PIECE + PAD))

    # 拼图块：从背景上抠出来，加一圈白边（浅色背景上也看得清）
    piece = Image.new("RGBA", (PIECE + PAD, PIECE + PAD), (0, 0, 0, 0))
    piece.paste(crop(background).convert("RGBA"), (0, 0), mask)
    ImageDraw.Draw(piece).rounded_rectangle(
        [0, 0, PIECE, PIECE], radius=8, outline=(255, 255, 255, 210), width=2
    )

    # 缺口：把背景上这一块调暗，再描一圈白边
    hole = ImageEnhance.Brightness(crop(background).convert("RGB")).enhance(0.45)
    background.paste(hole, (x, y), mask)
    ImageDraw.Draw(background).rounded_rectangle(
        [x, y, x + PIECE, y + PIECE], radius=8, outline=(255, 255, 255, 180), width=2
    )

    payload = {
        "background": _data_url(background),
        "puzzle": _data_url(piece),
        "width": WIDTH,
        "height": HEIGHT,
        "puzzle_size": PIECE,
        # 拼图图片本身是 PIECE + PAD 宽（右侧凸起 + 透明留白），前端按这个宽度
        # 显示，块才会和缺口一样大
        "puzzle_width": PIECE + PAD,
        "y": y,
        "tolerance": TOLERANCE,
        "expires_in": TTL_SECONDS,
    }
    return payload, x


# ---------- 会话记录与校验 ----------


def session_answer(value, kind: str) -> dict:
    """存进 session 的答案记录（带种类和时间戳）"""
    return {"kind": kind, "value": value, "at": time.time()}


def answer_is_fresh(answer: dict | None, now: float | None = None) -> bool:
    """答案还在有效期内吗

    过期的答案不再接受：否则打开一个登录页放半天，再慢慢暴力试同一个答案。
    """
    if not isinstance(answer, dict):
        return False
    issued_at = answer.get("at")
    if not isinstance(issued_at, (int, float)):
        return False
    return (now if now is not None else time.time()) - issued_at <= TTL_SECONDS


def verify_chars(answer: str | None, submitted) -> bool:
    """字符图/语音：忽略大小写与首尾空白（现在只有数字，留这层是为了以后换字符集）"""
    expected = str(answer or "").strip().lower()
    if not expected:
        return False
    return str(submitted or "").strip().lower() == expected


def verify_slide(answer: int | None, submitted) -> bool:
    """拖动位置：|提交值 - 答案| 在容差内就算对

    提交值按**原图坐标**算（前端用显示宽度换算过）。非数字、空值一律不通过。
    """
    if answer is None:
        return False
    try:
        value = float(str(submitted).strip())
    except (TypeError, ValueError):
        return False
    return abs(value - float(answer)) <= TOLERANCE
