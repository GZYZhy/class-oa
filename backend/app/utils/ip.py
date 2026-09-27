"""IP 地址与网段的处理。

只依赖标准库 ipaddress。这里的函数是「哪些 IP 可以封、哪些 IP 允许用通开密码」
这两件事的唯一判据，所以每个都刻意写得保守：
**判不准的时候一律返回「不可信 / 不匹配 / 不封」**，绝不猜。
"""

import ipaddress
import re
from functools import lru_cache

# 一次打一条警告就够，别在每次请求里刷屏
_warned: set[str] = set()


def _warn_once(text: str) -> None:
    if text not in _warned:
        _warned.add(text)
        print(f"[配置] {text}", flush=True)


def normalize_ip(raw: str) -> str | None:
    """把一个 IP 字符串规范化；不是合法 IP 就返回 None。

    - 砍掉 IPv6 的 zone id（fe80::1%eth0）—— 那玩意只在单机链路内有意义，
      跨网段传过来只会让同一个地址变成两个不同的字符串
    - **显式折叠** ::ffff:1.2.3.4 → 1.2.3.4：ipaddress 在 3.12 / 3.14 上对
      ipv4_mapped 的处理有过差异，不折叠的话同一台机器会产生两条互不匹配的记录
      （唯一约束是按字符串比的，挡不住这种「看着一样其实两行」）

    返回 None 是「这个字符串绝不写库、绝不封禁」的唯一判据。
    它顺手挡住 TestClient 的 "testclient" 和 get_client_ip 的 "unknown" 兜底值 ——
    **封了 "unknown" 等于把所有人一起封了**，而且唯一约束下还只有一行。
    """
    text = (raw or "").strip()
    if not text:
        return None
    # 先去掉 zone id 再解析（ipaddress 见到 % 会直接报错）
    text = text.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    # 折叠 IPv4-mapped IPv6
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return str(mapped)
    return str(addr)


@lru_cache(maxsize=256)
def parse_network(text: str):
    """单个 CIDR 串（或裸 IP）→ ipaddress 网段对象；解析不了返回 None。

    用 strict=False，所以 1.2.3.4/24 会被归一到 1.2.3.0/24 ——
    不归一的话「1.2.3.4/24」和「1.2.3.0/24」会是两个互不匹配的唯一键，
    管理员封了一个，另一个照样能登录。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return ipaddress.ip_network(raw, strict=False)
    except ValueError:
        return None


@lru_cache(maxsize=256)
def parse_address(text: str):
    """裸 IP 字符串 → ipaddress 地址对象；解析不了返回 None。

    **判「IP 落不落在网段里」必须用它，不能拿 parse_network 的结果去比。**

    CPython 的 IPv4Network.__contains__ 对网段参数是一律 return False 的
    （源码里那行注释就是 "dealing with another network"），只有传**地址对象**
    才走真正的掩码比较。而 ip_network("1.2.3.4", strict=False) 返回的是
    IPv4Network("1.2.3.4/32") —— 网段对象。所以拿它去 `in` 一个网段，
    不管两个网段是不是真的包含，答案永远是 False。

    这个坑踩起来很隐蔽：判定的结果不是报错，而是「什么都不匹配」。
    表现出来就是 TRUSTED_PROXIES 配了等于没配、封一个网段完全不起作用、
    「不能封禁自己」形同虚设（0.0.0.0/0 都拦不住）。第一次实现就栽在这儿，
    全项目的网段包含判定一度全是假的。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


@lru_cache(maxsize=16)
def parse_cidrs(text: str) -> tuple:
    """CIDR 串 → 网段元组。

    逗号或空白都当分隔符：NGINX_TRUSTED_PROXIES 那边是空格分隔的，
    运维极可能照着那个格式写；两种都收比让配错的人自己猜要省事。

    非法项跳过并打一行警告：配错一格不该让整个功能失效，
    但也不能静默 —— 否则「填了白名单却没生效」永远查不出来。

    返回元组（而不是列表）是为了配合 lru_cache —— 缓存的对象必须不可变。
    """
    nets = []
    for item in re.split(r"[,\s]+", (text or "").strip()):
        if not item:
            continue
        net = parse_network(item)
        if net is None:
            _warn_once(f"网段 {item!r} 解析失败，已跳过（其余配置照常生效）")
            continue
        nets.append(net)
    return tuple(nets)


def ip_in_cidrs(ip: str, nets) -> bool:
    """这个 IP 落在任一网段里吗。

    解析失败、nets 为空、类型对不上（v4 对 v6 网段）一律 False ——
    失败关闭。用 try/except 是因为跨 Python 版本对 v4/v6 混合比较的行为
    不保证一致。

    addr 必须是**地址对象**（parse_address），不能是 parse_network 出来的
    /32 网段对象 —— 后者 `in` 一个网段恒为 False，见 parse_address 的注释。

    拿地址之前先过一遍 normalize_ip：它会把 ::ffff:1.2.3.4 折成 1.2.3.4，
    否则那个 v4-mapped 地址会是个 IPv6Address，和 IPv4 网段根本没法比。
    """
    if not ip or not nets:
        return False
    norm = normalize_ip(ip)
    if norm is None:
        return False
    addr = parse_address(norm)
    if addr is None:
        return False
    for net in nets:
        try:
            if addr in net:
                return True
        except (TypeError, ValueError):
            continue
    return False


def normalize_target(raw: str) -> str | None:
    """把「手动封禁框里填的东西」规范化成可入库、可比较的字符串；非法返回 None。

    单个 IP 和 CIDR 网段都收：
    - 单个 IP 走 normalize_ip（含 v4-mapped 折叠），原样返回
    - 网段走 parse_network，返回 str()，也就是归一化到网络地址之后的形式

    返回 None 时调用方必须拒绝 —— 和 normalize_ip 一样，这是
    「绝不写库、绝不封禁」的唯一判据。
    """
    text = (raw or "").strip()
    if not text:
        return None
    if "/" in text:
        net = parse_network(text)
        return str(net) if net is not None else None
    return normalize_ip(text)


def target_matches(target: str, ip: str) -> bool:
    """这条封禁记录命中这个 IP 吗。

    裸 IP 比字符串（两边都规范化过），网段比包含关系。
    任何一个解析不了都返回 False —— 宁可漏封也不能错封，
    错封的代价是全班登不进来。
    """
    norm_ip = normalize_ip(ip)
    if norm_ip is None or not target:
        return False
    if "/" not in target:
        return target == norm_ip
    net = parse_network(target)
    if net is None:
        return False
    # 这里要是**地址对象**，不能是 parse_network 出来的 /32 网段。
    # 用错的话「封了一个网段」会完全不生效，等于这个功能没做 —— 见 parse_address 的注释
    addr = parse_address(norm_ip)
    if addr is None:
        return False
    try:
        return addr in net
    except (TypeError, ValueError):
        return False


def pick_client_ip(forwarded: str, nets) -> str | None:
    """从 X-Forwarded-For 里挑出真实客户端 IP。

    **从右往左扫，跳过可信网段，取第一个不可信的地址。**

    为什么是从右往左：nginx 配的是
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    它把**客户端自带的 XFF 原样拼在最左边**，把 nginx 自己算出来的真实 IP
    追加在最右边。所以：

        <攻击者塞的垃圾>, [...中间几层代理...], <真实客户端 IP>

    最左边是攻击者可控的，取最左边等于每次换个伪造值就能绕过一切按 IP 的防护。
    而从右往左遇到的第一批地址都是我们自己的代理，第一个「不是自己人」的
    才是真的客户端 —— 这正是 nginx 自己开启 real_ip_recursive 后的语义。

    全部可信 / 全部无法解析时返回 None，由调用方兜底。
    """
    if not forwarded or not nets:
        return None
    parts = [p.strip() for p in forwarded.split(",")]
    for raw in reversed(parts):
        ip = normalize_ip(raw)
        if ip is None:
            # 垃圾值：跳过，继续往左找
            continue
        if not ip_in_cidrs(ip, nets):
            return ip
    return None
