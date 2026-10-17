"""通行密钥（WebAuthn）测试

真后端 + 临时库，浏览器那半用软件认证器顶上：它按 WebAuthn 的字节格式
自己造注册 / 断言响应（ES256 签名），让 py_webauthn 真去验签 ——
不是为了证明库里那几个函数能跑，而是证明**服务端的期望值对得上**：
挑战、来源、RP ID、签名计数器、COSE 公钥，任何一处不一致都会在这里拦下。

覆盖：登记 → 列表 → 登出 → 用钥匙登录 → /me；错误密码拿不到选项；
挑战一次性且分登记/登录两种；同一把钥匙不能重复登记；管理员清除后钥匙失效；
**登录不输学号**：选项不点名凭据、按钥匙反查持有人、没登记的钥匙进不来；
登记必须要求可发现凭据（resident key）；添加 / 删除钥匙写进账号事件。

cd backend && python -m pytest tests/test_passkey.py -q
"""
import base64
import hashlib
import json
import os
import struct

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

PW = "initpass123"
ADMIN_NO = "2024000001"


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class SoftAuthenticator:
    """软件认证器：一把 P-256 私钥 + 一个自造的凭据 ID

    只实现服务端验证需要的部分：
    - 注册：attestation fmt=none，authData 里带 AAGUID、凭据 ID 和 COSE 公钥；
    - 登录：对 authData + sha256(clientDataJSON) 做 ECDSA-SHA256 签名。
    """

    def __init__(self, origin: str, rp_id: str):
        self.origin = origin
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.sign_count = 0

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": challenge,
                "origin": self.origin,
                "crossOrigin": False,
            },
            separators=(",", ":"),
        ).encode()

    def _cose_key(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,   # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: nums.x.to_bytes(32, "big"),
                -3: nums.y.to_bytes(32, "big"),
            }
        )

    def register(self, options: dict) -> dict:
        client_data = self._client_data("webauthn.create", options["challenge"])
        flags = 0x45  # UP（用户在场）+ UV（用户验证）+ AT（带凭据数据）
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
            + b"\x00" * 16  # AAGUID
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        encoded = _b64u(self.credential_id)
        return {
            "id": encoded,
            "rawId": encoded,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _b64u(client_data),
                "attestationObject": _b64u(attestation),
                "transports": ["internal"],
            },
        }

    def login(self, options: dict) -> dict:
        client_data = self._client_data("webauthn.get", options["challenge"])
        self.sign_count += 1
        flags = 0x05  # UP + UV
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
        )
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        encoded = _b64u(self.credential_id)
        return {
            "id": encoded,
            "rawId": encoded,
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": _b64u(client_data),
                "authenticatorData": _b64u(auth_data),
                "signature": _b64u(signature),
                "userHandle": None,
            },
        }


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录的后端

    PUBLIC_BASE_URL 显式置空：否则仓库根 .env 里那份线上地址会漏进来，
    服务端会期望 https://1.example.com 作为来源，而测试客户端是 http://127.0.0.1。
    """
    inst = backend(db="passkey.db", BOOTSTRAP_PASSWORD=PW, PUBLIC_BASE_URL="")
    assert inst.login(password=PW).status_code == 200
    r = inst.client.post(
        "/api/students",
        json={
            "student_no": ADMIN_NO,
            "name": "甲",
            "id_card": "110101200601010001",
        },
    )
    assert r.status_code == 200, r.text
    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text

    inst.logout()
    assert inst.login(ADMIN_NO, "010001").status_code == 200
    return inst


def _authenticator(b) -> SoftAuthenticator:
    origin = str(b.client.base_url).rstrip("/")
    return SoftAuthenticator(origin=origin, rp_id="127.0.0.1")


def _register(b, auth: SoftAuthenticator, label: str = "测试钥匙", password: str = "010001"):
    options = b.client.post(
        "/api/auth/passkeys/register/options",
        json={"password": password, "label": label},
    )
    assert options.status_code == 200, options.text
    return b.client.post(
        "/api/auth/passkeys/register/verify",
        json={"password": password, "label": label, "credential": auth.register(options.json())},
    )


def _login_options(b):
    """取登录选项：不再带学号，服务器返回空 allowCredentials"""
    return b.client.post(
        "/api/auth/passkeys/login/options",
        json={"remember": True},
    )


def _login(b, auth: SoftAuthenticator):
    options = _login_options(b)
    assert options.status_code == 200, options.text
    return b.client.post(
        "/api/auth/passkeys/login/verify",
        json={"remember": True, "credential": auth.login(options.json())},
    )


def _events(b) -> list[str]:
    """「我的日志 → 登录与账号操作」里的事件名，最近的在前"""
    r = b.client.get("/api/auth/my-logs", params={"events_page_size": 50})
    assert r.status_code == 200, r.text
    return [e["event"] for e in r.json()["events"]]


def test_register_login_and_list(b):
    """登记一把钥匙 → 列表里看得到 → 登出后用它登录 → 会话真的生效"""
    auth = _authenticator(b)

    r = _register(b, auth)
    assert r.status_code == 200, r.text

    r = b.client.get("/api/auth/passkeys")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["max_count"] == 10
    assert len(data["items"]) == 1
    assert data["items"][0]["label"] == "测试钥匙"
    assert data["items"][0]["last_used_at"] is None

    b.logout()
    assert b.client.get("/api/auth/me").status_code == 401

    options = _login_options(b)
    assert options.status_code == 200, options.text
    assert options.json()["allowCredentials"] == [], "不点名任何凭据，由浏览器列出本机的钥匙"

    r = _login(b, auth)
    assert r.status_code == 200, r.text
    assert r.json()["student_no"] == ADMIN_NO

    me = b.client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["student_no"] == ADMIN_NO

    # 用过的钥匙要记一笔：列表里的「最后使用」不再为空
    items = b.client.get("/api/auth/passkeys").json()["items"]
    assert items[0]["last_used_at"]


def test_register_options_need_correct_password(b):
    """登录态可能是别人留下的，登记钥匙必须再确认一次密码"""
    auth = _authenticator(b)
    r = b.client.post(
        "/api/auth/passkeys/register/options",
        json={"password": "wrongpass1", "label": "x"},
    )
    assert r.status_code == 400, r.text
    assert "密码不正确" in r.text

    # 错密码没消耗掉挑战，补一个正确的还能继续
    assert _register(b, auth).status_code == 200


def test_challenge_is_single_use(b):
    """挑战只能用一次：重放同一个响应会被挡在挑战校验这一步"""
    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200
    b.logout()

    options = _login_options(b)
    payload = {
        "remember": True,
        "credential": auth.login(options.json()),
    }
    first = b.client.post("/api/auth/passkeys/login/verify", json=payload)
    assert first.status_code == 200, first.text

    replay = b.client.post("/api/auth/passkeys/login/verify", json=payload)
    assert replay.status_code == 400, replay.text
    assert "超时" in replay.text


def test_register_challenge_cannot_be_used_to_login(b):
    """拿登记的挑战去走登录校验，必须被 kind 拦住"""
    auth = _authenticator(b)
    options = b.client.post(
        "/api/auth/passkeys/register/options",
        json={"password": "010001", "label": "测试钥匙"},
    )
    assert options.status_code == 200, options.text

    r = b.client.post(
        "/api/auth/passkeys/login/verify",
        json={
            "remember": True,
            # 响应是按登录格式造的，但服务端会话里存的是登记挑战
            "credential": auth.login({"challenge": options.json()["challenge"]}),
        },
    )
    assert r.status_code == 400, r.text


def test_same_credential_cannot_register_twice(b):
    """同一把钥匙登记两次一律拒绝，不悄悄覆盖已有记录"""
    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200

    r = _register(b, auth)
    assert r.status_code == 400, r.text
    assert "已经登记过" in r.text

    assert len(b.client.get("/api/auth/passkeys").json()["items"]) == 1


def test_register_requires_discoverable_credential(b):
    """登记必须要求可发现凭据：钥匙里不存账号，浏览器就列不出来，免账号登录无从谈起"""
    r = b.client.post(
        "/api/auth/passkeys/register/options",
        json={"password": "010001", "label": "测试钥匙"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["authenticatorSelection"]["residentKey"] == "required"


def test_login_options_never_enumerate_credentials(b):
    """库里明明有钥匙，登录选项里也不点名 —— 选哪把由浏览器决定，接口不暴露账号"""
    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200

    b.logout()
    r = _login_options(b)
    assert r.status_code == 200, r.text
    assert r.json()["allowCredentials"] == []


def test_unregistered_credential_is_rejected(b):
    """没在本站登记过的钥匙，即使拿到了合法挑战也登不进来"""
    auth = _authenticator(b)
    options = _login_options(b)
    r = b.client.post(
        "/api/auth/passkeys/login/verify",
        json={"remember": True, "credential": auth.login(options.json())},
    )
    assert r.status_code == 400, r.text


def test_key_identifies_its_owner_without_student_no(b):
    """两把钥匙分属两个账号：登出后选谁的钥匙就登谁，前端不用传学号"""
    other_no = "2024000002"
    auth1 = _authenticator(b)
    assert _register(b, auth1).status_code == 200

    # 建第二个学生（自动建号，初始密码 = 身份证后 6 位），登录后登记第二把钥匙
    r = b.client.post(
        "/api/students",
        json={
            "student_no": other_no,
            "name": "乙",
            "id_card": "110101200601010002",
        },
    )
    assert r.status_code == 200, r.text
    b.logout()
    assert b.login(other_no, "010002").status_code == 200
    auth2 = _authenticator(b)
    assert _register(b, auth2, label="乙的钥匙", password="010002").status_code == 200

    # 第二把 → 第二个人
    b.logout()
    r = _login(b, auth2)
    assert r.status_code == 200, r.text
    assert r.json()["student_no"] == other_no
    assert b.client.get("/api/auth/me").json()["student_no"] == other_no

    # 第一把 → 第一个人，两把不会串
    b.logout()
    r = _login(b, auth1)
    assert r.status_code == 200, r.text
    assert r.json()["student_no"] == ADMIN_NO


def test_admin_can_clear_and_key_stops_working(b):
    """管理员清除后：列表为空，旧钥匙再也登不进去，密码不受影响"""
    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200

    r = b.client.delete(f"/api/admin/users/{ADMIN_NO}/passkeys")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1

    assert b.client.get("/api/auth/passkeys").json()["items"] == []

    b.logout()
    r = _login(b, auth)
    assert r.status_code == 400, r.text

    # 密码这条退路始终在
    assert b.login(ADMIN_NO, "010001").status_code == 200


def test_passkey_login_skips_two_factor(b):
    """开了二次验证也能直接用钥匙登录：钥匙本身已经是第二因素"""
    from app.utils.totp import code_at

    r = b.client.post("/api/auth/2fa/totp/begin", json={"password": "010001"})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = b.client.post("/api/auth/2fa/totp/confirm", json={"code": code_at(secret)})
    assert r.status_code == 200, r.text

    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200

    b.logout()
    # 密码登录被拦在第二因素
    r = b.login(ADMIN_NO, "010001")
    assert r.json()["two_factor_required"] is True
    assert b.client.get("/api/auth/me").status_code == 401

    # 钥匙登录不经过那一关，直接完成
    r = _login(b, auth)
    assert r.status_code == 200, r.text
    assert b.client.get("/api/auth/me").status_code == 200


def test_key_add_and_delete_are_logged(b):
    """添加 / 删除通行密钥都落在「登录与账号操作」里，带 IP"""
    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200

    r = b.client.get("/api/auth/my-logs")
    first = r.json()["events"][0]
    assert first["event"] == "passkey_add"
    assert first["ip"], "账号事件要记下操作时的 IP"

    key_id = b.client.get("/api/auth/passkeys").json()["items"][0]["id"]
    r = b.client.delete(f"/api/auth/passkeys/{key_id}")
    assert r.status_code == 200, r.text
    assert _events(b)[0] == "passkey_delete"


def test_only_own_key_can_be_deleted(b):
    """删别人的钥匙：404，而不是删掉或报 500"""
    auth = _authenticator(b)
    assert _register(b, auth).status_code == 200

    # 直接写一条属于不存在用户的记录，模拟别人的钥匙
    b.run(
        "INSERT INTO passkey_credentials "
        "(user_id, credential_id, public_key, sign_count, transports, label, backed_up, created_at) "
        "VALUES (?, ?, ?, 0, '', '别人的', 0, datetime('now'))",
        9999,
        "foreign-credential",
        b"\x00",
    )
    foreign_id = b.rows(
        "SELECT id FROM passkey_credentials WHERE credential_id = ?", "foreign-credential"
    )[0][0]

    r = b.client.delete(f"/api/auth/passkeys/{foreign_id}")
    assert r.status_code == 404, r.text
    assert len(b.client.get("/api/auth/passkeys").json()["items"]) == 1
