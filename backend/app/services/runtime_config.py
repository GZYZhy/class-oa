"""运行时配置：把「运维能改、改了立刻生效」的那部分设置从环境变量搬到数据库

管理员在「系统管理 → 运维」里改，存 runtime_settings 表。读取方式没有变 ——
仍然是 `settings.smtp_host` 这种属性访问，只是**在启动时和保存后**把库里的值
写回 settings 对象，于是 config.smtp_enabled()、email_service、bark_service
这些既有读取点一行都不用改。

为什么只搬一部分：
  * 机密（通开密码、会话密钥、VAPID 私钥）：后台可改等于给管理员账号失守之后
    再留一扇门，必须只认环境变量；
  * 安全边界（可信代理网段、通开密码白名单）：改这里就能伪造来源 IP、绕过
    封禁，属于「被入侵后能扩权」的配置，同样只认环境变量；
  * 构建期配置（SITE_* 品牌、HEAD_INJECT、高德 Key）：由前端容器启动时注入，
    后端改了对页面没有任何影响，只会造成两处不一致；
  * 部署形态（DATABASE_URL、CORS、Session Cookie 属性）：改了必须重启，
    放在这里会让人以为保存就生效。
这些项在页面上以只读清单展示，写清「改哪里、怎么生效」。

多实例：本进程内的 settings 在保存时立刻更新；别的实例由 RuntimeConfigMiddleware
每 REFRESH_SECONDS 秒回查一次库（只查一次全表，量很小），因此最迟一分钟内一致。
"""

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings
from ..models.runtime_setting import RuntimeSetting

# 密文项在接口里的占位符。前端看到它表示「已配置」，原样提交回来时视为不修改
MASK = "********"
# 前端点「清除」时提交这个哨兵，表示删掉库里的覆盖值、回落到环境变量
CLEAR = "__CLEAR__"

# 配置项元数据。key 必须与 config.Settings 的字段名一致，写回时才找得到属性
@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    kind: str = "text"          # text | int | secret | choice
    help: str = ""
    choices: tuple[str, ...] = ()
    min: int | None = None
    max: int | None = None


GROUPS = ("站点与链接", "邮件通知（SMTP）", "人机验证", "登录安全", "办件文档")

FIELDS: tuple[Field, ...] = (
    # ---------- 站点与链接 ----------
    Field(
        "app_name", "应用名称", "站点与链接",
        help="接口文档标题与推送通知里的来源名。页面上的班级名由前端环境变量决定，改这里不影响页面",
    ),
    Field(
        "public_base_url", "本站对外地址", "站点与链接",
        help="如 https://oa.example.com。用于推送里的校徽图标和点击跳转；留空则通知不带图标",
    ),
    Field(
        "bark_server", "Bark 推送地址", "站点与链接",
        help="默认 https://api.day.app；自建 bark-server 时改这里，必须带 http:// 或 https://",
    ),
    Field(
        "vapid_subject", "Web Push 联系地址", "站点与链接",
        help="推送服务出问题时联系谁，形如 mailto:you@example.com 或 https://example.com",
    ),
    # ---------- 邮件通知 ----------
    Field("smtp_host", "SMTP 主机", "邮件通知（SMTP）", help="留空 = 邮件渠道整体关闭"),
    Field(
        "smtp_port", "SMTP 端口", "邮件通知（SMTP）", kind="int", min=0, max=65535,
        help="0 = 按加密方式推导（ssl→465 / starttls→587 / none→25）",
    ),
    Field(
        "smtp_security", "加密方式", "邮件通知（SMTP）", kind="choice",
        choices=("ssl", "starttls", "none"),
        help="none 仅供内网测试：账号密码会明文过网络",
    ),
    Field("smtp_user", "发信账号", "邮件通知（SMTP）"),
    Field(
        "smtp_password", "授权码", "邮件通知（SMTP）", kind="secret",
        help="QQ / 163 邮箱填授权码，不是登录密码",
    ),
    Field("smtp_from", "发件人地址", "邮件通知（SMTP）", help="留空则用发信账号"),
    # ---------- 人机验证 ----------
    Field(
        "turnstile_site_key", "Turnstile Site Key", "人机验证",
        help="两个都配才启用；都留空继续用内置算术验证码",
    ),
    Field("turnstile_secret_key", "Turnstile Secret Key", "人机验证", kind="secret"),
    # ---------- 登录安全 ----------
    Field(
        "login_ban_threshold", "失败几次自动封禁", "登录安全", kind="int", min=0, max=1000,
        help="同一个 IP 在窗口内失败满多少次就封禁；0 = 关闭自动封禁",
    ),
    Field(
        "login_fail_window_minutes", "失败计数窗口（分钟）", "登录安全", kind="int", min=1, max=1440,
        help="验证码和自动封禁共用这一个窗口",
    ),
    Field(
        "login_ban_minutes", "封禁时长（分钟）", "登录安全", kind="int", min=1, max=525600,
    ),
    # ---------- 办件文档 ----------
    Field(
        "ev_pass_grade", "专业年级", "办件文档",
        help="电动车通行证表格里「专业年级」整格的内容，如「示例专业2026级」",
    ),
    Field("ev_pass_graduation", "毕业时间", "办件文档", help="如「2099年6月」"),
    Field("ev_pass_address", "住址", "办件文档", help="全班统一住同一栋公寓时填这里"),
    Field(
        "school", "校名", "办件文档",
        help="后端生成的 Word / PDF 落款用；页面上的校名由前端 SITE_SUBTITLE 决定",
    ),
)

FIELD_BY_KEY = {field.key: field for field in FIELDS}

# 只读清单：这些项**故意不从后台改**，页面上只展示它们的存在与约束
ENV_ONLY: tuple[tuple[str, str, str], ...] = (
    (
        "MASTER_PASSWORD / TWO_FACTOR_MASTER_CODE / BOOTSTRAP_PASSWORD",
        "应急口令",
        "一次性钥匙。只放在 .env，用完清空并重启；后台可改等于留了长期后门",
    ),
    (
        "SESSION_SECRET_KEY / VAPID_PRIVATE_KEY",
        "会话与推送密钥",
        "机密，只放 .env 或 data/ 下的密钥文件；泄露即可伪造登录、冒充本站发推送",
    ),
    (
        "TRUSTED_PROXIES / MASTER_PASSWORD_ALLOW_IPS",
        "IP 信任边界",
        "改这里就能伪造来源 IP、绕过封禁与白名单，属于被入侵后可扩权的配置",
    ),
    (
        "DATABASE_URL / CORS_ORIGINS / SESSION_COOKIE_SECURE / SESSION_MAX_AGE",
        "部署形态",
        "改了必须重启，且属于部署决策，不适合在后台随手改",
    ),
    (
        "SCHEDULE_GEO_TITLES",
        "校区坐标映射",
        "部署私有数据（JSON 数组），只放在 .env",
    ),
    (
        "SITE_NAME / SITE_SHORT_NAME / SITE_SUBTITLE / SITE_COLLEGE / SITE_MAJOR / SITE_FOOTER",
        "前端品牌",
        "由前端容器启动时注入，改完要 docker compose up -d frontend（restart 不重新读 .env）",
    ),
    (
        "HEAD_INJECT / AMAP_JS_KEY / AMAP_SECURITY_CODE",
        "前端注入与地图 Key",
        "同样由前端容器注入，改完要 up -d frontend",
    ),
)

# 启动时的生效值（环境变量或代码默认）。用它做「回落默认」的依据 ——
# settings 的属性一旦被数据库值覆盖，就再也找不回环境变量里那个值了
_ENV_DEFAULTS: dict[str, object] = {field.key: getattr(settings, field.key, "") for field in FIELDS}

_lock = threading.Lock()
_cache_at = 0.0
# 多实例时别的进程最迟这么久之后能看到新值
REFRESH_SECONDS = 60


def _to_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _default(field: Field) -> object:
    return _ENV_DEFAULTS.get(field.key, "")


def _coerce(field: Field, raw: str) -> object:
    """库里存的字符串 → settings 属性要的类型。值不合法时抛 ValueError（带中文说明）"""
    if field.kind == "int":
        try:
            number = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f"{field.label}必须是整数")
        if field.min is not None and number < field.min:
            raise ValueError(f"{field.label}不能小于 {field.min}")
        if field.max is not None and number > field.max:
            raise ValueError(f"{field.label}不能大于 {field.max}")
        return number

    text = raw.strip()
    if field.kind == "choice" and text not in field.choices:
        raise ValueError(f"{field.label}只能是 {' / '.join(field.choices)} 之一")

    if field.key in ("public_base_url", "bark_server"):
        if text and not text.startswith(("http://", "https://")):
            raise ValueError(f"{field.label}必须带 http:// 或 https://")
        return text.rstrip("/") if field.key == "public_base_url" and text else text

    if field.key == "vapid_subject":
        # pywebpush 会拿它做签名，格式不对时是运行时才炸，这里先拦住
        if text and not (text.startswith("mailto:") or text.startswith("https://")):
            raise ValueError("Web Push 联系地址必须是 mailto: 或 https:// 开头")
    return text


def get(key: str):
    """当前生效值（已经被数据库覆盖过的就直接是覆盖后的值）"""
    return getattr(settings, key)


def load(db: Session) -> int:
    """把库里的覆盖值写回 settings，返回实际生效的覆盖项数

    库里没有的项回落到启动时的环境变量 / 代码默认值。幂等，可以反复调。
    """
    global _cache_at
    with _lock:
        rows = {row.key: row.value for row in db.query(RuntimeSetting).all()}
        applied = 0
        for field in FIELDS:
            raw = rows.get(field.key, "")
            if raw == "":
                setattr(settings, field.key, _default(field))
                continue
            try:
                setattr(settings, field.key, _coerce(field, raw))
                applied += 1
            except ValueError:
                # 库里存着坏值（改过库、或旧版本遗留）：宁可回落默认值，也不要让
                # 整个进程起不来 —— 页面上能看到该项来源已回落
                setattr(settings, field.key, _default(field))
        _cache_at = time.time()
        return applied


def maybe_refresh() -> None:
    """中间件每 REFRESH_SECONDS 秒调一次，让多实例也能看到别处保存的配置

    任何异常都吞掉：配置刷新失败不该让正常请求 500。
    """
    if time.time() - _cache_at < REFRESH_SECONDS:
        return
    from ..database import SessionLocal  # 函数内导入：database 模块在导入时就会读 settings

    db = SessionLocal()
    try:
        load(db)
    except Exception:  # noqa: BLE001
        pass
    finally:
        db.close()


def snapshot(db: Session) -> dict:
    """给运维页用的完整视图：分组、当前值（密文打码）、来源、最后修改人"""
    rows = {row.key: row for row in db.query(RuntimeSetting).all()}
    fields = []
    for field in FIELDS:
        row = rows.get(field.key)
        if row is not None and row.value != "":
            value, source = row.value, "database"
        else:
            value = _default(field)
            value = "" if value is None else _to_str(value)
            source = "environment" if os.environ.get(field.key.upper(), "").strip() else "default"

        if field.kind == "secret" and value:
            value = MASK

        fields.append({
            "key": field.key,
            "label": field.label,
            "group": field.group,
            "kind": field.kind,
            "help": field.help,
            "choices": list(field.choices),
            "min": field.min,
            "max": field.max,
            "value": value,
            "source": source,
            "updated_at": row.updated_at if row is not None else None,
            "updated_by_name": row.updated_by_name if row is not None else "",
        })

    return {
        "groups": list(GROUPS),
        "fields": fields,
        "env_only": [
            {"keys": keys, "label": label, "reason": reason}
            for keys, label, reason in ENV_ONLY
        ],
        "version": {
            "app_version": settings.app_version,
            "app_name": settings.app_name,
        },
    }


def save(
    db: Session,
    values: dict[str, object],
    *,
    updated_by_no: str,
    updated_by_name: str,
) -> list[str]:
    """保存一批配置，返回真正有变化的键

    规则：
      * 只认 FIELDS 里的键，别的直接报错（说明前端写错了字段名）；
      * 空串 = 删掉覆盖值，回落到环境变量；
      * 密文项收到 MASK = 不修改，收到 CLEAR = 删掉覆盖值。
    """
    unknown = [key for key in values if key not in FIELD_BY_KEY]
    if unknown:
        raise ValueError(f"不认识的配置项：{'、'.join(unknown)}")

    changed: list[str] = []
    for key, raw in values.items():
        field = FIELD_BY_KEY[key]
        row = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()

        text = "" if raw is None else str(raw)
        if field.kind == "secret" and text == MASK:
            continue  # 前端把打码值原样提交回来了，代表「不改」

        if text == "" or text == CLEAR:
            if row is not None:
                db.delete(row)
                changed.append(key)
            continue

        # 先按类型校验一遍，坏值连库都不进
        _coerce(field, text)
        if row is None:
            db.add(RuntimeSetting(
                key=key,
                value=text,
                updated_by_no=updated_by_no,
                updated_by_name=updated_by_name,
            ))
            changed.append(key)
        elif row.value != text:
            row.value = text
            row.updated_at = datetime.now()
            row.updated_by_no = updated_by_no
            row.updated_by_name = updated_by_name
            changed.append(key)

    db.flush()
    load(db)
    return changed
