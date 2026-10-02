"""邮箱地址的格式判定

**只此一处定义。** 学生提交邮箱变更申请（schemas/change_request.py）、保存通知
邮箱（api/auth.py）、查收件人、发信前（都在 services/email_service.py）全都走
这一个判据。分头写迟早会出现「审批入口放行的地址，发信时被静默跳过」——
那个人就是收不到邮件，而且谁也不知道为什么。

放在 utils 而不是 email_service 里，是为了避开循环 import：
services/student_service.py 已经 import 了 schemas，schema 再反向 import
services 就成环了。（和 notify_text.py 里那份 clip 是同一个理由。）

判据写得比较严，是有具体原因的：

- `students.email` 来自 Excel 导入和学生的变更申请，库里**已经有脏数据**了
  （`3681914218qq.com`、`1113808118qq.com`，都是缺 `@` 的那种），不校验就会
  一直往 SMTP 送无效收件人；
- 更要紧的是它可能带 `\\r\\n`。这个地址最终要拼进 SMTP 的 `To:` 头，不挡就是
  头注入 —— 一个学生把变更申请的邮箱填成 `a@b.com\\nBcc: 全班`，班委审批通过后
  就等于给这条通知开了一条群发通道。
"""

import re

# 故意不用 email.utils 的宽松解析：那个连 "a@b" 这种没有顶级域的写法都收，
# 而 SMTP 发到它只会被拒。这里要求必须有点号分隔的顶级域。
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def is_valid_email(address: str) -> bool:
    """这个地址能不能拿去发信。判不准一律 False，不给「猜一个」的机会。

    每次都 strip：库里存的值可能带空格（Excel 导入的常见产物），
    不 strip 的话 `" a@b.com"` 会被判非法而静默丢信。
    """
    return bool(_EMAIL_RE.match((address or "").strip()))
