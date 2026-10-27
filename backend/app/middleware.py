"""
动态调整会话 Cookie 的有效期。

Starlette 的 SessionMiddleware 只有一个全局 max_age，
但我们要支持「保持登录 7 天」和「不保持（浏览器关了就失效）」两种模式。

做法：
  1. 把 SessionMiddleware 的全局 max_age 设成 7 天（签名有效期的上限）
  2. 这个中间件在响应阶段检查 session 里的 _remember 标志：
       - 有 → Cookie Max-Age 保持 7 天（不动它）
       - 没有 → 把 Set-Cookie 里的 Max-Age 去掉，变成 session cookie
         （浏览器关闭就失效，重新打开要重新登录）

为什么不直接把 SessionMiddleware 的 max_age 改成动态的？
  因为 Starlette 不支持，要改就得重写中间件，侵入性太大。
  改响应头最省心，也不影响验签逻辑。

安全性说明：
  就算有人用浏览器开发者工具把 session cookie 改成持久化的，
  服务端签名的 max_age 还是 7 天，7 天后照样失效，不会无限延长。

**注册顺序有要求**：本中间件必须注册在 SessionMiddleware 之后（后注册的在外层），
否则读不到 Set-Cookie。原因见下面 dispatch 里的注释 —— 这里踩过坑。
"""

import re

from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RememberMeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 必须在外层（注册在 SessionMiddleware 之后）才读得到下面的 Set-Cookie：
        # oa_session 那个头是 SessionMiddleware 在**响应阶段**才追加的，
        # 它一旦包在本中间件外面，等这里拿到响应时那个头还没写上去 ——
        # 于是 found 恒为 False，整个中间件一行都不改，
        # 结果就是所有人都拿到 SessionMiddleware 那个 7 天的持久 Cookie，
        # 「不保持登录」勾选框彻底失效。这是本中间件的经典坑，改顺序前先想清楚。
        session = request.session
        remember = session.get("_remember", False) if session else False

        # 找到 oa_session 的 Set-Cookie 头，调整 Max-Age
        new_cookies = []
        found = False
        for cookie in response.headers.getlist("set-cookie"):
            if cookie.startswith("oa_session="):
                found = True
                if remember:
                    # 保持登录：Max-Age 设为 7 天（604800 秒）
                    # 先去掉原有的 Max-Age（如果有），再加新的
                    new_val = re.sub(r';\s*Max-Age=\d+', '', cookie, flags=re.IGNORECASE)
                    new_val = new_val + "; Max-Age=604800"
                    new_cookies.append(new_val)
                else:
                    # 不保持：去掉 Max-Age，变成 session cookie（浏览器关了就没）
                    new_val = re.sub(r';\s*Max-Age=\d+', '', cookie, flags=re.IGNORECASE)
                    new_cookies.append(new_val)
            else:
                new_cookies.append(cookie)

        if found:
            # MutableHeaders 只有 getlist，**没有 setlist**（starlette 0.38 实测如此），
            # 原来那行 setlist 一旦真被执行就是 AttributeError。
            # 要整体替换只能先 del 再逐条 append：del 会一次清掉该 key 的全部值，
            # 删完按原顺序（new_cookies 就是按原顺序攒的）补回去，顺序不变。
            del response.headers["set-cookie"]
            for cookie in new_cookies:
                response.headers.append("set-cookie", cookie)

        return response


# 天然幂等的方法。0-RTT 重放它们不会造成任何副作用，拦了纯属牺牲性能
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RejectEarlyDataMiddleware(BaseHTTPMiddleware):
    """拒掉从 TLS 1.3 early data（0-RTT）里发来的写请求。

    nginx 开了 ssl_early_data 之后，客户端可以把请求捎在握手的第一个包里发上来，
    省一个往返。代价是这段数据**完全没有任何防重放保护** —— 攻击者只要能在链路上
    看到它，就能原封不动地再发一遍。落到本站的场景就是「一个登录 POST 被重放」
    「一次提交被重放」。

    nginx 用 `proxy_set_header Early-Data $ssl_early_data;` 把「这个请求来自
    early data」告诉后端（Early-Data 是 RFC 8470 定义的头）。这里只做最保守的一件事：
    写请求 + Early-Data: 1 → 回 425 Too Early。浏览器收到 425 会自动去掉 0-RTT
    重发一次，用户是无感的。

    只拦写请求：GET / HEAD / OPTIONS 天然幂等，重放没有意义。
    """

    async def dispatch(self, request: Request, call_next):
        if (
            request.headers.get("early-data") == "1"
            and request.method not in _SAFE_METHODS
        ):
            return JSONResponse(
                status_code=status.HTTP_425_TOO_EARLY,
                content={"detail": "请求需在完整握手后重发，请重试"},
            )
        return await call_next(request)


class RuntimeConfigMiddleware(BaseHTTPMiddleware):
    """让多实例部署也能看到别处保存的运维配置

    配置保存在哪个进程，那个进程立刻生效（runtime_config.save 里直接 load）。
    其它实例靠这一层每 REFRESH_SECONDS 秒回查一次库；没到点的话只是一次
    time.time() 比较，不碰数据库。

    单实例部署（Dockerfile 里的 uvicorn 没带 --workers）时它基本什么都不做，
    但留着才能保证「以后加多实例不用回头想起还有这么一层」。
    """

    async def dispatch(self, request: Request, call_next):
        from .services import runtime_config  # 函数内导入：避免 config → services 的循环

        runtime_config.maybe_refresh()
        return await call_next(request)


class DefaultCacheControlMiddleware(BaseHTTPMiddleware):
    """给**没有自己表态**的接口补一句 Cache-Control: no-store。

    这件事以前是 nginx 干的（前端 nginx.conf 里 location ^~ /api/ 那句
    add_header Cache-Control "no-store"）。问题在于 add_header 是**追加**而不是覆盖：
    后端特意给照片设的「private, max-age=31536000」会被它顶成两个 Cache-Control 头，
    而 no-store 只要出现一个就生效 —— 于是那张一年的缓存白设了，
    学生名单页三十多张照片每进一次就重下一遍（弱网下这是几 MB 的白流量）。

    规矩挪到这一层，只补默认值、不覆盖已经表过态的：
      · 绝大多数接口什么也没设 → 补 no-store，和原来一样，隐私数据进不了任何缓存；
      · 照片、课表订阅源这类自己设了的 → 原样放行（照片是靠 URL 里的文件名做版本号，
        换图后地址会变，所以敢缓存一年）。

    注意是加在**响应阶段**：那会儿 FileResponse 已经把自己的头写好了，
    才判断得出「有没有表态」。BaseHTTPMiddleware 会把内层响应的头原样带上来
    （starlette 的 response.raw_headers = message["headers"]），所以这里看得见。
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response
