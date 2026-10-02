"""通知文本的公共约定：长度上限和截断

这几个常量和 `clip()` 原本定义在 bark_service 里，但它们是**所有渠道共用的口径**，
不是 Bark 专有的：手机通知栏就那么宽，邮件主题同理，webhook 的载荷也不该无限长。
原先 webpush_service 是从 bark_service 反向 import 的，再加两个渠道会变成
「四个模块都去引用 Bark」，所以搬到这里。

bark_service 仍然把这些名字再导出一次（`from ..utils.notify_text import ...`），
所以 `services/__init__.py` 和外部调用方（如 api/auth.py 取 clip）都不用改。
"""

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
