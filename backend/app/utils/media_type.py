"""猜下发文件时该带哪个 Content-Type

不能只靠标准库的 mimetypes：Python 3.12 内置的那张表里**没有** .docx / .xlsx / .pptx
（只有老的 .doc / .xls / .ppt），而 python:slim 镜像里也不一定有 /etc/mime.types。
两边都没命中时 Starlette 会兜底成 text/plain（0.38 那版就是拿它兜底），
浏览器照着这个类型给文件补后缀 —— 结果就是下载下来的 Word 文档变成了 xxx.txt。

所以本站会遇到的类型写死在下面这张表里，其余再交给 mimetypes，最后才 octet-stream。
"""

import mimetypes
from pathlib import Path

# 资料、证明材料、附件允许上传的类型，加上几个常见的音视频
_TYPES = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".zip": "application/zip",
}


def guess_media_type(*names: str | None) -> str:
    """按顺序猜：先查表，再问 mimetypes，都猜不出来才 application/octet-stream

    可以传多个名字，配合下面的「磁盘名没有扩展名就退回原始名」的取法：
    存盘名是没有扩展名的 UUID，原始名还带着后缀时，靠它才猜得出来。
    兜底不用 text/plain —— 认不出来就当二进制，总比让浏览器按文本存强。
    """
    for name in names:
        if not name:
            continue
        ext = Path(name).suffix.lower()
        if ext in _TYPES:
            return _TYPES[ext]
        guessed = mimetypes.guess_type(name)[0]
        if guessed:
            return guessed
    return "application/octet-stream"
