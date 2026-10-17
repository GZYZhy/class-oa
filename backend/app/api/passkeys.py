"""通行密钥（Passkey / WebAuthn）登录

密码之外多一种登录方式：用手机或电脑自带的指纹、面容、系统 PIN 解锁一把钥匙，
不用再输密码。密码**始终保留** —— 换手机、丢手机时还能用它进门，管理员也能
一键清掉某人的全部通行密钥。

两件不显然的事：

1. **挑战（challenge）存在服务端会话里，一次性、限时十分钟**。挑战本身不是秘密，
   但必须由服务端签发并在验证时比对；让前端回传一个「我刚生成的挑战」，
   等于把防重放交给攻击者来保证。
2. **RP ID / 期望来源从配置或浏览器 Origin 推导**。两个班级各是一个独立实例，
   要让钥匙只对本站有效：1.example.com 的钥匙不该在 2.example.com 上被提示出来。
   所以 RP ID 取完整主机名，不取父域 example.com。
3. **登录不需要先输学号**。登记时要求「可发现凭据」，钥匙里带着账号；登录时
   浏览器列出本站的钥匙让用户挑，服务器在验证那一步按凭据 ID 反查持有人。
   凭据 ID 由认证器随机生成、全表唯一，反查结果就是这次登录的账号。
"""
import time
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    options_to_json_dict,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..config import settings
from ..database import get_db
from ..models import PasskeyCredential, User
from ..schemas import (
    PasskeyListResponse,
    PasskeyLoginOptionsRequest,
    PasskeyLoginVerifyRequest,
    PasskeyRegisterOptionsRequest,
    PasskeyRegisterVerifyRequest,
)
from ..services import account_name, get_active_ban
from ..utils.security import verify_password
from . import auth as auth_api
from .deps import get_client_ip, require_cookie_auth

router = APIRouter(prefix="/api/auth/passkeys", tags=["通行密钥"])

# 一个人最多登记 10 把：手机、平板、两台电脑、备用钥匙……再多就不是钥匙而是仓库了
MAX_PASSKEYS = 10
# 挑战十分钟后作废。按一次指纹只要几秒；放宽到十分钟是给条件式 UI 用的 ——
# 页面打开后钥匙会一直挂在账号框的自动填充里，用户可能过一会儿才点它。
# 挑战仍是一次性的、绑在当前会话上，被截获也无法在别处重放
CHALLENGE_TTL = 600
_CHALLENGE_KEY = "webauthn_challenge"


def _site(request: Request) -> tuple[str, str]:
    """返回 (期望来源, RP ID)

    优先用 PUBLIC_BASE_URL（线上由 .env 指定，是唯一权威）；
    没配时用浏览器的 Origin（本地开发走 vite 代理时就是 http://localhost:5173）；
    再没有就退回请求自身的地址（测试里的 HTTP 客户端不带 Origin）。
    """
    base = (settings.public_base_url or "").strip().rstrip("/")
    if not base:
        base = (request.headers.get("origin") or "").strip().rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")

    parsed = urlsplit(base)
    if not parsed.scheme or not parsed.hostname:
        raise HTTPException(status_code=400, detail="无法确认本站地址，请刷新后重试")
    return f"{parsed.scheme}://{parsed.netloc}", parsed.hostname


def _save_challenge(
    request: Request, kind: str, challenge: bytes, **extra
) -> None:
    """把挑战塞进会话：kind 区分「登记」和「登录」，防止拿登记挑战去登录"""
    request.session[_CHALLENGE_KEY] = {
        "kind": kind,
        "challenge": bytes_to_base64url(challenge),
        "exp": time.time() + CHALLENGE_TTL,
        **extra,
    }


def _take_challenge(request: Request, kind: str) -> tuple[bytes, dict]:
    """取出并**立刻清掉**挑战。用过一次就不能再用，重放直接失败"""
    data = request.session.pop(_CHALLENGE_KEY, None)
    if not data or data.get("kind") != kind or data.get("exp", 0) < time.time():
        raise HTTPException(status_code=400, detail="验证已超时，请重新发起")
    return base64url_to_bytes(data["challenge"]), data


def _passkeys_of(db: Session, user_id: int) -> list[PasskeyCredential]:
    return (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.user_id == user_id)
        .order_by(PasskeyCredential.created_at)
        .all()
    )


def _check_ban(db: Session, ip: str) -> None:
    """封禁闸门和密码登录保持一致：被封的 IP 连挑战都不该拿到"""
    ban = get_active_ban(db, ip)
    if ban:
        raise HTTPException(status_code=403, detail=auth_api._ban_detail(ban))


@router.get("", response_model=PasskeyListResponse, summary="列出我的通行密钥")
def list_passkeys(
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    return PasskeyListResponse(items=_passkeys_of(db, user.id), max_count=MAX_PASSKEYS)


@router.post("/register/options", summary="登记通行密钥：第一步，取选项")
def register_options(
    data: PasskeyRegisterOptionsRequest,
    request: Request,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """要再输一次密码才给选项：登录态可能是别人借你电脑留下的，不能因此就让他
    给自己塞一把长期钥匙"""
    if not verify_password(data.password, user.password_hash, user.password_salt):
        raise HTTPException(status_code=400, detail="密码不正确")

    existing = _passkeys_of(db, user.id)
    if len(existing) >= MAX_PASSKEYS:
        raise HTTPException(
            status_code=400,
            detail=f"最多登记 {MAX_PASSKEYS} 把通行密钥，请先删掉不用的",
        )

    _, rp_id = _site(request)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.site_name or settings.app_name,
        user_id=str(user.id).encode(),
        user_name=user.student_no,
        user_display_name=account_name(db, user),
        # 要求「可发现凭据」（resident key）：钥匙里同时存下本站的账号，
        # 登录时浏览器就能把本机的钥匙列出来让用户挑，不用先输学号。
        # RP ID 仍是完整主机名，另一套班级实例的钥匙不会串到这里
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        # 同一把钥匙已经登记过时，让浏览器自己拦下来，免得出现两行同名记录
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id))
            for p in existing
        ],
    )
    _save_challenge(request, "register", options.challenge)
    return options_to_json_dict(options)


@router.post("/register/verify", summary="登记通行密钥：第二步，验证并保存")
def register_verify(
    data: PasskeyRegisterVerifyRequest,
    request: Request,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    """**不校验 credential_id 是否重复后再覆盖**：重复登记一律拒绝。
    浏览器按 excludeCredentials 本来就会拦，真走到这里说明有问题，
    悄悄换成另一把等于把「谁占了这个位置」搞乱。"""
    challenge, _ = _take_challenge(request, "register")
    origin, rp_id = _site(request)

    try:
        verified = verify_registration_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except Exception:
        # 不把库的异常原文回给前端：里面会带「挑战不匹配 / 来源不对」这类细节，
        # 对正常用户没有帮助，对探测者却是提示
        raise HTTPException(status_code=400, detail="通行密钥登记失败，请重试")

    credential_id = bytes_to_base64url(verified.credential_id)
    if (
        db.query(PasskeyCredential.id)
        .filter(PasskeyCredential.credential_id == credential_id)
        .first()
    ):
        raise HTTPException(status_code=400, detail="这把通行密钥已经登记过了")

    transports = (data.credential.get("response") or {}).get("transports") or []
    db.add(
        PasskeyCredential(
            user_id=user.id,
            credential_id=credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=",".join(str(t) for t in transports)[:100],
            label=(data.label or "").strip()[:50],
            backed_up=bool(verified.credential_backed_up),
        )
    )
    db.commit()
    return {"message": "已添加通行密钥"}


@router.delete("/{passkey_id}", summary="删除我的一把通行密钥")
def delete_passkey(
    passkey_id: int,
    user: User = Depends(require_cookie_auth),
    db: Session = Depends(get_db),
):
    row = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.id == passkey_id, PasskeyCredential.user_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="没有找到这把通行密钥")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.post("/login/options", summary="通行密钥登录：第一步，取选项")
def login_options(
    data: PasskeyLoginOptionsRequest,
    request: Request,
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    """不点名任何账号：allowCredentials 留空，由浏览器列出本机上属于本站的钥匙，
    用户挑一把、过指纹 / 面容 / PIN 即可。谁登录留到第二步按凭据反查。"""
    _check_ban(db, ip)

    _, rp_id = _site(request)
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _save_challenge(request, "login", options.challenge, remember=data.remember)
    return options_to_json_dict(options)


@router.post("/login/verify", summary="通行密钥登录：第二步，验证并登录")
def login_verify(
    data: PasskeyLoginVerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
    ip: str = Depends(get_client_ip),
):
    _check_ban(db, ip)
    challenge, meta = _take_challenge(request, "login")
    origin, rp_id = _site(request)

    # 谁登录由**钥匙本身**决定：rawId 与登记时存的 credential_id 是同一个
    # base64url 串，且全表唯一。反查到的持有人就是这次登录的账号，前端不回传学号，
    # 也就不存在「拿 A 的挑战去登 B」的问题
    credential_id = data.credential.get("rawId") or data.credential.get("id")
    row = (
        db.query(PasskeyCredential)
        .filter(PasskeyCredential.credential_id == credential_id)
        .first()
    )
    user = db.query(User).filter(User.id == row.user_id).first() if row else None
    if not user:
        raise HTTPException(status_code=400, detail="通行密钥验证失败，请重试")

    try:
        verified = verify_authentication_response(
            credential=data.credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="通行密钥验证失败，请重试")

    # 克隆检测：只有两边都非零、且计数没有增长时才当成可疑。
    # 同步型钥匙（iCloud / Google 钥匙串）在别的设备上加完再回来，计数经常就是 0，
    # 一刀切「必须增长」会把正常用户挡在门外
    if row.sign_count and verified.new_sign_count and verified.new_sign_count <= row.sign_count:
        raise HTTPException(status_code=400, detail="通行密钥验证失败，请重试")

    # 冻结检查放在验证之后：验证失败时统一文案，不透露「这个号存在且被冻结了」
    if user.is_frozen:
        raise HTTPException(status_code=400, detail="账号已被冻结，请联系管理员")

    row.sign_count = verified.new_sign_count
    row.last_used_at = datetime.now()
    row.backed_up = bool(verified.credential_backed_up)

    # 和密码登录走同一个收尾：最近登录时间、登录事件、会话代次、保持登录都一致
    auth_api.complete_login(request, db, user, ip, bool(meta.get("remember", True)))
    return auth_api.build_user_info(db, user, auth_api._student_of(db, user))
