"""字节数 → 人话（12.3 KB）

分享卡片和文件体检都要展示文件大小，两处共用一个函数：
各写一份的话，「0 字节」这种边界迟早只在一处处理对。
"""


def human_size(size: int | None) -> str:
    number = int(size or 0)
    if number <= 0:
        return "0 B"
    if number < 1024:
        return f"{number} B"
    kb = number / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    return f"{mb / 1024:.1f} GB"
