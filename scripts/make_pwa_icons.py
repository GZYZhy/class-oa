#!/usr/bin/env python3
"""
PWA 图标生成脚本
用 frontend/public/logo.png 生成「添加到主屏」需要的四种图标

    python3 scripts/make_pwa_icons.py

换校徽时重跑一次，然后**把产物一起提交**（图标是构建产物里唯一进版本库的东西，
因为服务器上不装 Pillow，Docker 构建阶段也不该为了四个图标多装一个依赖）。

生成到 frontend/public/icons/：
    icon-192.png            192×192  普通图标（透明底）
    icon-512.png            512×512  普通图标（透明底），装到桌面时用
    icon-maskable-512.png   512×512  安卓自适应图标，四周留安全区
    apple-touch-icon.png    180×180  iOS 主屏图标（iOS 不接受透明，铺白底）
"""

import os
import sys

SOURCE = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "logo.png")
TARGET_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "icons")

# 带底色的两种图标都铺白底。
# 不用主题色 #409EFF：校徽本身是深红圆徽，压在高饱和度的蓝底上两色相冲，
# 边缘发闷；白底和校徽的对比最干净，也和 manifest 的 background_color 一致。
# （普通图标保持透明底，桌面自己会给它配背景）
WHITE = (255, 255, 255, 255)

# 自适应图标只保证中间这块（直径 80%）一定可见，所以校徽缩到 60% 更保险
MASKABLE_RATIO = 0.6
APPLE_RATIO = 0.86


def square(im):
    """把非正方形的图补成正方形

    透明的边角料，不动原图 —— 直接拉伸会让校徽变形（圆徽压成椭圆最明显）。
    """
    from PIL import Image

    size = max(im.size)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return canvas


def on_background(im, size, color, ratio):
    """把校徽按比例居中放到纯色底上，四周留出边距"""
    from PIL import Image

    canvas = Image.new("RGBA", (size, size), color)
    inner = int(size * ratio)
    logo = im.resize((inner, inner), Image.LANCZOS)
    offset = (size - inner) // 2
    # 用自身当遮罩贴上去：校徽自带的透明边缘不会盖住底色，也不会带出黑框
    canvas.paste(logo, (offset, offset), logo)
    return canvas


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("❌ 未安装 Pillow，无法生成图标。可执行：pip install Pillow")
        return 1

    if not os.path.isfile(SOURCE):
        print(f"❌ 找不到源图：{os.path.abspath(SOURCE)}")
        return 1

    src = Image.open(SOURCE).convert("RGBA")
    print(f"源图 {os.path.basename(SOURCE)}：{src.width}×{src.height}")
    base = square(src)

    os.makedirs(TARGET_DIR, exist_ok=True)
    jobs = [
        # (文件名, 尺寸, 画法, 说明)
        ("icon-192.png", 192, lambda: base.resize((192, 192), Image.LANCZOS), "普通图标"),
        ("icon-512.png", 512, lambda: base.resize((512, 512), Image.LANCZOS), "普通图标（大）"),
        ("icon-maskable-512.png", 512,
         lambda: on_background(base, 512, WHITE, MASKABLE_RATIO), "安卓自适应（带安全区）"),
        ("apple-touch-icon.png", 180,
         lambda: on_background(base, 180, WHITE, APPLE_RATIO), "iOS 主屏（白底）"),
    ]

    for name, _, build, note in jobs:
        path = os.path.join(TARGET_DIR, name)
        build().save(path, optimize=True)
        print(f"✅ {name:<24} {os.path.getsize(path) // 1024:>3} KB  {note}")

    print(f"\n完成，共生成 {len(jobs)} 个图标：{os.path.abspath(TARGET_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
