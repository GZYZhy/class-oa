"""Webhook 地址的安全判定（SSRF 防护）

`users.webhook_url` 是本项目**唯一**一处「用户自己填地址、服务器替他去发请求」
的地方。没有这层防护，任何一个学生账号都等于一个能探测内网的跳板：填
`https://192.168.1.1/`、`https://[::1]:6379/`、`https://169.254.169.254/`
（云厂商元数据接口）就能让后端替他连过去，响应内容还会作为「发送失败原因」
落在日志里。

判据分两层，缺一不可：

1. **地址形态**：只收 https、不许内嵌凭据、不许有控制字符或空格；
2. **主机名解析出来的每一个 IP 都必须是公网地址**。

任何一层不过就整体拒绝，并给出能直接显示给用户的中文原因。

三个地方共用这一个函数：保存接口（PUT）、测试接口（POST /test）、真正发送前。
共用是刻意的 —— 分成三份写，迟早有一份忘了更新，而漏掉的那份就是绕过口。
"""

import ipaddress
import re
import socket
import urllib.parse

from .ip import normalize_ip, parse_address

# 用户填的地址里出现任何控制字符（含 \r \n \t）或空格就直接拒绝。
# 不只是为了整洁：CRLF 是 URL 解析歧义和请求头注入的经典入口，
# 而「https://a.com/ x」这种带空格的地址在不同解析器里可能被理解成两个不同的东西。
_CONTROL_CHARS = re.compile(r"[\x00-\x20\x7f]")

# 显式黑名单。**只补 is_global 判断不准的那几段，不重列私网** ——
# 私网（10/8、172.16/12、192.168/16、127/8、169.254/16、fc00::/7 ……）
# 在现代 Python 上 is_global 本来就是 False，列全了反而容易漏抄一个。
# 这里四条都是实测出来的「is_global 说 True 但其实不能放行」的：
_DENY_NETS = tuple(ipaddress.ip_network(text) for text in (
    # 组播。实测 224.0.0.1 / 239.255.255.250 / ff02::1 的 is_global 全是 True，
    # 但往组播地址发 POST 是能让同网段一堆机器一起收到的东西，绝不可能是合法 webhook
    "224.0.0.0/4",
    "ff00::/8",
    # NAT64 网段：64:ff9b::7f00:1 里内嵌的就是 127.0.0.1，而它自身不是 ipv4_mapped，
    # normalize_ip 折叠不到，只能靠这条网段挡
    "64:ff9b::/96",
    # 6to4 中继：发给它等于让中继替我们把请求转发到内嵌的 IPv4
    "192.88.99.0/24",
))


def _addr_is_public(text: str) -> bool:
    """这个 IP 文本可以让我们去连吗

    先过 normalize_ip（砍 zone id、折叠 ::ffff:1.2.3.4）—— **必须复用 utils.ip
    里那一份**，别在这儿另写一遍 v4-mapped 的处理：3.12 和 3.14 对 ipv4_mapped
    的语义并不一致，两处各写一份就会出现「这个入口拦不住、那个入口拦得住」。

    is_global 单独用是不够的（见 _DENY_NETS 的注释），所以在它之外还要显式
    排除组播 / 保留 / 未指定 / 回环 / 链路本地，再叠一层网段黑名单。

    任何解析不了的输入一律 False —— 判不准就当不安全，不给「猜一个」的机会。
    """
    norm = normalize_ip(text)
    if norm is None:
        return False
    addr = parse_address(norm)
    if addr is None:
        return False
    try:
        if not (
            addr.is_global
            and not addr.is_multicast
            and not addr.is_reserved
            and not addr.is_unspecified
            and not addr.is_loopback
            and not addr.is_link_local
        ):
            return False
        # 跨版本比较 v4 地址和 v6 网段会抛 TypeError，所以先按版本对齐
        for net in _DENY_NETS:
            if addr.version == net.version and addr in net:
                return False
    except (TypeError, ValueError):
        # 类型对不上 = 判不准 = 不放行
        return False
    return True


def is_allowed_webhook_url(url: str, *, resolve: bool = True) -> tuple[bool, str]:
    """这个 webhook 地址允许服务器去请求吗

    返回 `(是否允许, 拒绝原因)`；允许时原因为空串，拒绝时原因可以直接
    直接回给用户（PUT 接口的 400 就这么用）。

    resolve=False 只做形态检查、不打 DNS —— 给不联网的单元测试用，
    以及以后需要「快速预检」的场景。**生产路径一律用默认的 True**：
    不做解析就等于允许 `https://内部域名.example` 这种绕过。

    残余风险（已知、不修）：这里是「先解析校验，再由 urllib 自己解析一次去连」，
    两次解析之间域名可以变（DNS rebinding）。真要堵得把连接 pin 到已校验的那个
    IP 上，代码量翻三倍 —— 对一个班级系统不值得。攻击者还得先控制一个域名和
    DNS 服务器，成本远高于他直接找台能上网的机器自己打。
    """
    raw = (url or "").strip()
    if not raw:
        return False, "地址不能为空"

    if _CONTROL_CHARS.search(raw):
        return False, "地址里不能有空格或换行等控制字符"

    try:
        parsed = urllib.parse.urlsplit(raw)
        # .hostname 和 .port 都会在地址畸形时抛 ValueError（如 https://[::1)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False, "地址格式不正确"

    if parsed.scheme != "https":
        # 沿用 schemas/auth.py 里订阅地址的先例：只认 https。
        # http 的 webhook 不只是「不加密」，而是让中间人可以直接改我们发出去的内容
        return False, "只支持 https:// 开头的地址"

    if parsed.username or parsed.password:
        # https://user:pass@evil.com 里的 evil.com 才是真正被连的主机，
        # 但一眼看上去像是 user 那个域名 —— 老钓鱼手法，直接不收
        return False, "地址里不能内嵌用户名或密码"

    if not host:
        return False, "地址里没有主机名"

    # 主机名本身就是 IP 字面量时**不需要 DNS，所以 resolve=False 也要判**。
    # 少了这一步，resolve=False 就成了「IP 直连一律放行」，而直连 IP
    # 恰好是攻击者最省事的一档（不用买域名、不用等解析）
    if normalize_ip(host) is not None:
        if not _addr_is_public(host):
            return False, "这个地址指向内网或本机，出于安全不能填"
        return True, ""

    if not resolve:
        return True, ""

    try:
        # proto=IPPROTO_TCP 把结果限定在 TCP 上，和后面 urllib 真正做的连接一致。
        # 注意这个调用**不受 socket 超时保护**（解析是 libc 在做），
        # 死掉的 DNS 服务器会让它卡上几秒 —— 前端 axios 超时 15 秒，够用
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, "这个域名解析不了，请检查拼写"
    except Exception:
        # 解析器抽风、host 里塞了非法字节等，一律当解析失败
        return False, "这个域名解析不了，请检查拼写"

    if not infos:
        return False, "这个域名没有解析到任何地址"

    # **每一条都要是公网**，不是「有一条是公网就放行」——
    # 后者等于把「到底连哪个 IP」的选择权交给对方：他只要让域名同时解析到
    # 8.8.8.8 和 127.0.0.1，我们校验时看见公网就放行，urllib 连的时候
    # 挑中哪个全看它自己的心情
    for info in infos:
        if not _addr_is_public(info[4][0]):
            return False, "这个地址指向内网或本机，出于安全不能填"

    return True, ""
