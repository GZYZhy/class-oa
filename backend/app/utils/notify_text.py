"""通知文本的公共约定：长度上限和截断

这几个常量和 `clip()` 原本定义在 bark_service 里，但它们是**所有渠道共用的口径**，
不是 Bark 专有的：手机通知栏就那么宽，邮件主题同理，webhook 的载荷也不该无限长。
原先 webpush_service 是从 bark_service 反向 import 的，再加两个渠道会变成
「四个模块都去引用 Bark」，所以搬到这里。

bark_service 仍然把这些名字再导出一次（`from ..utils.notify_text import ...`），
所以 `services/__init__.py` 和外部调用方（如 api/auth.py 取 clip）都不用改。
"""

import re

# 标题长度上限：手机通知栏放不下更长的，与其被系统从尾巴硬切（屏幕上出现半句话，
# 还看不出被截过），不如我们自己截好并明确告诉用户后面还有
TITLE_LIMIT = 40
BODY_LIMIT = 120


def clip(text: str, limit: int = 60) -> str:
    """把用户输入的文字截短，超出部分用省略号收尾

    顺带把换行换成空格 —— 这一条同时是**邮件头的防线**：Subject 里混进 \r\n
    就是 SMTP 头注入。任何要拼进邮件头的用户输入都先过这里。
    """
    # \r 和 \n 都要换成空格：头注入不只是 "\r\n"，单独一个 \r 也能撑开新的一行
    text = (text or "").strip().replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def markdown_to_text(markdown: str) -> str:
    """Markdown 正文 → 单行纯文本

    用来做「手机通知栏里的那一句正文」和 RSS 条目的摘要 —— 这两处都没有渲染
    Markdown 的余地，`##`、`![]()` 原样送过去就是一堆符号。

    去掉标题/引用/列表的行首标记、围栏代码块、链接与图片的语法（只留可读的
    文字，图片留 alt），以及 `**加粗**` `` `代码` `` 这类行内标记。
    各段之间用空格拼：直接粘起来会变成「第一句第二句」，比多一个空格难看得多。
    """
    parts: list[str] = []
    in_fence = False
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        # 围栏代码块整块丢掉：` ``` ` 里的代码原样念出来没有意义
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue

        # 先摘行内标记、再摘行首标记，顺序不能反：反了会把 `**加粗**` 的星号
        # 当列表符号剥掉一个，剩下一个孤零零的 `*`
        text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)  # 链接/图片只留文字
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)            # **加粗**
        text = re.sub(r"__(.+?)__", r"\1", text)                # __加粗__
        text = re.sub(r"\*(.+?)\*", r"\1", text)                # *斜体*
        text = re.sub(r"`([^`]*)`", r"\1", text)                # `代码`
        text = re.sub(r"~~(.+?)~~", r"\1", text)                # ~~删除线~~
        text = text.lstrip("#>*+- \t").strip()
        if text:
            parts.append(text)

    return " ".join(parts)
