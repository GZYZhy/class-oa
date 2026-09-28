"""PDF 不可见水印服务

用 PyMuPDF (fitz) 实现基于「渲染模式 3」的不可见文本水印：
- 把水印令牌以 render_mode=3（既不描边也不填充）写入 PDF 内容流
- 肉眼完全不可见，但 page.get_text() 可以直接提取
- 纯文本 PDF 有效，原文流转可靠（重存盘不丢）

令牌格式：OA-WM:<file_id>:<user_no>:<timestamp_unix>
- 纯 ASCII，避开中文字体嵌入/ToUnicode 乱码问题
- 用固定前缀 OA-WM: 方便提取时正则匹配

额外冗余层：同令牌也写入 PDF 元数据 /Info 的 Keywords 字段。
（元数据容易被清除，只作为辅助，不作为唯一依据）
"""

import io
import re
import time

import pymupdf as fitz  # PyMuPDF（新版本包名是 pymupdf，fitz 作为别名兼容旧代码）

# 水印令牌前缀，提取时按此前缀捞
TOKEN_PREFIX = "OA-WM:"
# 令牌正则：OA-WM:文件ID:学号:时间戳
TOKEN_PATTERN = re.compile(rf"{TOKEN_PREFIX}(\d+):(\w+):(\d+)")


def make_watermark_token(file_id: int, user_no: str, timestamp: int | None = None) -> str:
    """构造水印令牌"""
    if timestamp is None:
        timestamp = int(time.time())
    return f"{TOKEN_PREFIX}{file_id}:{user_no}:{timestamp}"


def parse_watermark_token(token: str) -> dict | None:
    """解析水印令牌，返回 {file_id, user_no, timestamp}，解析失败返回 None"""
    m = TOKEN_PATTERN.search(token)
    if not m:
        return None
    return {
        "file_id": int(m.group(1)),
        "user_no": m.group(2),
        "timestamp": int(m.group(3)),
    }


def add_invisible_watermark(pdf_bytes: bytes, token: str) -> bytes:
    """给 PDF 每页加不可见水印，返回打了水印的字节

    实现：每页用 fontsize=1 + render_mode=3（不可见），把令牌循环铺若干行。
    字号设成 1pt、间距拉大，既保证存在于内容流中，又不会影响正常文本的提取。
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page in doc:
        rect = page.rect
        # 每页铺 6 行、每行重复 4 次令牌，抗局部裁剪
        # 行间距约为页面高度 1/6，每行从左到右均匀分布
        rows = 6
        cols = 4
        fontsize = 1.0
        # 用内置 Base-14 字体 helv（Helvetica），所有 PDF viewer 都认，不需要嵌入

        for r in range(rows):
            y = rect.y0 + (r + 0.5) * (rect.height / rows)
            for c in range(cols):
                x = rect.x0 + (c + 0.5) * (rect.width / cols)
                # render_mode=3: 既不描边也不填充，不可见但保留在内容流中
                page.insert_text(
                    (x, y),
                    token,
                    fontsize=fontsize,
                    fontname="helv",
                    render_mode=3,
                    color=(0, 0, 0),
                )

    # 冗余层：把令牌写进元数据 Keywords
    # 用 | 分隔，多个令牌时可以全部塞进去（理论上一个文件只加一次，留冗余是为了稳）
    old_keywords = doc.metadata.get("keywords", "") or ""
    if token not in old_keywords:
        new_keywords = f"{old_keywords}|{token}" if old_keywords else token
        doc.set_metadata({"keywords": new_keywords})

    out = io.BytesIO()
    doc.save(out, deflate=True, garbage=3)
    doc.close()
    return out.getvalue()


def extract_watermark(pdf_bytes: bytes) -> str | None:
    """从 PDF 中提取水印令牌，找不到返回 None

    优先级：内容流文本 > 元数据 Keywords。
    只要找到一个符合格式的令牌就返回。
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return None

    # 1. 从内容流文本中找（render_mode=3 的文本也会被 get_text() 拿出来）
    for page in doc:
        text = page.get_text()
        m = TOKEN_PATTERN.search(text)
        if m:
            doc.close()
            return m.group(0)

    # 2. 从元数据里找（冗余层）
    keywords = doc.metadata.get("keywords", "") or ""
    m = TOKEN_PATTERN.search(keywords)
    if m:
        doc.close()
        return m.group(0)

    doc.close()
    return None
