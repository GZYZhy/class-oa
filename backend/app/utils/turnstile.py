"""Cloudflare Turnstile 的服务端校验

登录页的人机验证有两套：内置的算术题（utils/captcha.py）和这个。
配了 .env 里的两个 key 就用 Turnstile，没配就还是算术题 ——
判定在 config.turnstile_enabled()，这里只管「拿 token 问 Cloudflare 通没通过」。

写法整套照搬 services/bark_service.py：stdlib urllib（零新依赖）、模块级 TIMEOUT、
两段式 except（HTTPError 单独读响应正文）、print 打日志、**绝不抛异常**。
校验是登录流程上的一环，但不能因为它本身出错就把人挡在门外。

关于「放行」这个产品决策：
  服务器连不上 Cloudflare、或错误码说明是我们自己没配好时，一律**放行**并打日志。
  理由是这个系统的主要风险是「全班登不进来」，而不是「机器人多试几次密码」。
  真正该拒绝的只有一种：Cloudflare 明确说这个 token 不行。
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from ..config import settings

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# 单次请求超时秒数。和 Bark 取同一个值，理由也一样：
# 前端 axios 的超时是 15 秒，这里拖太久用户看到的是「网络错误」而不是真实原因。
TIMEOUT = 5

# 这几个错误码的意思是「我们这边没配好」，不是用户没通过验证：
#   invalid/missing-input-secret —— secret key 填错或漏填
#   bad-request                  —— 我们发出去的请求格式不对
#   invalid-widget-id / invalid-parsed-secret —— secret 对应的 widget 不存在
# 撞上这些一律放行，否则 secret 里多一个字符就能把全班挡在门外，
# 而且从用户视角看跟「系统坏了」完全分不出来。日志里会写清楚是哪种。
OUR_FAULT = {
    "invalid-input-secret",
    "missing-input-secret",
    "bad-request",
    "invalid-widget-id",
    "invalid-parsed-secret",
}


def verify(token: str, remote_ip: str = "") -> bool:
    """校验前端交回来的 Turnstile token，返回「这次登录放不放行」

    True  = Cloudflare 说通过                       → 正常放行
    True  = 连不上 / 响应读不懂 / 错误码属于我们没配好  → 放行，打一行日志
    False = Cloudflare 明确说这个 token 不行         → 只有这一种情况拒绝

    token 是一次性的，同一个 token 验第二次会拿到 timeout-or-duplicate；
    调用方（登录接口）在每次登录失败后都要让前端 reset 控件换个新 token。
    """
    token = (token or "").strip()
    if not token:
        # 调用方不会走到这里（没 token 就不该调），兜底按未通过处理
        return False

    data = {"secret": settings.turnstile_secret_key, "response": token}
    # remoteip 是可选参数，Cloudflare 拿它做风控参考。取不到真实 IP 时宁可不传，
    # 传一个 "unknown" 反而是条脏数据
    if remote_ip and remote_ip != "unknown":
        data["remoteip"] = remote_ip

    try:
        # Request 构造时会解析 URL，放 try 里面免得异常穿出去（和 Bark 同一个理由）
        request = urllib.request.Request(
            VERIFY_URL,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        # 只打 str(exc) 会丢掉响应正文，线上就只剩「HTTP Error 400」这种没法查的日志
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"[Turnstile] 校验接口返回 HTTP {exc.code}，本次放行：{detail}", flush=True)
        return True
    except Exception as exc:
        # 网络不通、DNS 解析不了、超时、证书不受信都会走到这里。
        # 内地网络下这是最可能发生的一种，放行 + 留一行日志，别把全班挡在外面
        print(f"[Turnstile] 校验服务不可达，本次放行：{exc!r}", flush=True)
        return True

    if body.get("success") is True:
        return True

    codes = body.get("error-codes") or []
    if any(code in OUR_FAULT for code in codes):
        print(
            f"[Turnstile] 配置有问题（{'/'.join(codes) or '无错误码'}），"
            "本次放行，请检查 TURNSTILE_SECRET_KEY",
            flush=True,
        )
        return True

    # 到这儿说明是 token 本身不行：伪造、过期（300 秒）、或者已经被用过一次
    print(f"[Turnstile] 人机验证未通过：{'/'.join(codes) or '无错误码'}", flush=True)
    return False
