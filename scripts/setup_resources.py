#!/usr/bin/env python3
"""
预置资料安装脚本
把校徽/团徽、打印名单、常用表格复制到后端 data/downloads 目录

源素材不放在项目里（体积大、且含校内文件），由命令行指定所在目录：

    python3 scripts/setup_resources.py 素材目录 [更多素材目录...]

脚本会到这些目录里挨个查找下面 FILES 中登记的源文件名，找不到就跳过并提示。
"""

import os
import shutil
import subprocess
import sys
import tempfile

TARGET_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "downloads")

# 徽章类 PNG 源图动辄 40MB，装进来前先缩到 1200px 并量化调色板
PNG_MAX_PX = 1200
PNG_QUALITY = "80-95"

# 需要压缩的源文件名（这些是透明底 PNG，不能转 JPG，否则镂空处会变黑）
PNG_NAMES = {"校徽图片.png", "团徽图片.png"}

# 源文件名 → 目标文件名（源文件在各素材目录中按此名字查找）
FILES = [
    ("工大-透明-圆形.png", "校徽图片.png"),
    ("团徽.png", "团徽图片.png"),
    ("打印用-统26-1.xlsx", "打印用-统26-1.xlsx"),
    ("会议纪要-新.pdf", "会议纪要-新.pdf"),
    # 「资料下载」里给学生手填的空白表。系统生成的那张（填好学生信息、带签字、带水印）
    # 是 app/utils/leave_pdf.py 用 reportlab 画出来的，跟这份没有关系，也不会被这个脚本覆盖
    ("请假审批表.docx", "请假审批表.docx"),
    ("文件批示表.pdf", "文件批示表.pdf"),
]


def find_source(name: str, src_dirs: list[str]) -> str | None:
    """在给定的素材目录里按文件名查找源文件，返回第一个命中的绝对路径"""
    for d in src_dirs:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def compress_png(path: str) -> None:
    """把大尺寸透明 PNG 缩到 PNG_MAX_PX 并量化调色板，原地覆盖

    优先用 pngquant（libimagequant，会正确保留 alpha 通道）；
    没装则退回 Pillow：颜色量化与透明度分开处理，alpha 原样保留。
    """
    try:
        from PIL import Image
    except ImportError:
        print("   ⚠️  未安装 Pillow，跳过压缩。可执行：pip install Pillow")
        return

    im = Image.open(path).convert("RGBA")
    if max(im.size) <= PNG_MAX_PX and os.path.getsize(path) < 2 * 1024 * 1024:
        return  # 已经够小，不折腾

    small = im.resize((PNG_MAX_PX, PNG_MAX_PX), Image.LANCZOS)

    if shutil.which("pngquant"):
        # pngquant 直接读磁盘文件，先落一份临时的
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            small.save(tmp_path)
            subprocess.run(
                ["pngquant", f"--quality={PNG_QUALITY}", "--speed", "1", "--strip",
                 "--force", "--output", path, tmp_path],
                check=True,
            )
        finally:
            os.remove(tmp_path)
    else:
        # 颜色量化与透明度分开处理：整块 RGBA 一起量化会把 alpha 也当颜色，透明度全丢
        out = small.convert("RGB").quantize(colors=256, method=Image.FASTOCTREE).convert("RGBA")
        out.putalpha(small.getchannel("A"))
        out.save(path, optimize=True)


def main() -> int:
    src_dirs = sys.argv[1:]
    if not src_dirs:
        print(__doc__.strip())
        print("\n错误：请至少指定一个素材目录")
        return 1

    src_dirs = [os.path.abspath(os.path.expanduser(d)) for d in src_dirs]
    for d in src_dirs:
        if not os.path.isdir(d):
            print(f"❌ 素材目录不存在：{d}")
            return 1

    os.makedirs(TARGET_DIR, exist_ok=True)
    count = 0
    missing = []

    for src_name, dst_name in FILES:
        src = find_source(src_name, src_dirs)
        if src is None:
            missing.append(src_name)
            continue

        dst = os.path.join(TARGET_DIR, dst_name)
        shutil.copy2(src, dst)
        extra = ""
        if dst_name in PNG_NAMES:
            before = os.path.getsize(dst)
            compress_png(dst)
            extra = f"，压缩 {before // 1024} KB → {os.path.getsize(dst) // 1024} KB"
        print(f"✅ {dst_name} ({os.path.getsize(dst) // 1024} KB){extra}")
        count += 1

    if missing:
        print(f"\n⚠️  以下 {len(missing)} 个源文件在指定目录中没找到，已跳过：")
        for name in missing:
            print(f"   - {name}")

    print(f"\n完成，共安装 {count} 份资料")
    return 0


if __name__ == "__main__":
    sys.exit(main())
