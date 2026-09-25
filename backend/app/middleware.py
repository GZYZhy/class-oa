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
"""

import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RememberMeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 只处理设置了 oa_session cookie 的响应
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
            response.headers.setlist("set-cookie", new_cookies)

        return response
