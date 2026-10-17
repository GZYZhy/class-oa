"""二次验证测试

真后端 + 临时库；邮件那一路在测试进程里起一个**假 SMTP 服务器**，真的走一遍
smtplib 的 EHLO → AUTH → DATA，再把邮件正文里的验证码取出来填回登录框。
TOTP 直接用 app.utils.totp 算出当前时间步的码 —— 服务端和测试用的是同一个
纯函数，但正确性由 test_totp_math 里的 RFC 6238 官方测试向量兜底。

覆盖：邮件开启 → 登出 → 登录要第二因素 → 输错 → 输对；重发冷却；
TOTP 开启 → 登录；恢复码一次性；错误次数用尽；管理员清除；关闭后恢复密码直登。

cd backend && python -m pytest tests/test_two_factor.py -q
"""
import email
import re
import socket
import threading
import time
from email import policy

import pytest

from app.utils.totp import STEP, code_at, code_for_step, generate_secret, matches

PW = "initpass123"
ADMIN_NO = "2024000001"
LOGIN_PW = "010001"      # setup/finish 之后管理员的密码（身份证后 6 位）
MASTER_CODE = "246813"   # 测试后端配的二次验证万能码


# ---------- 假 SMTP ----------


class FakeSMTP:
    """够 smtplib 用就行的小服务器：收信、记下正文、一律放行 AUTH"""

    def __init__(self):
        self.messages: list[bytes] = []
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self.port = self._sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        with conn, conn.makefile("rwb") as f:
            f.write(b"220 localhost ESMTP\r\n")
            f.flush()
            in_data = False
            buffer: list[bytes] = []
            while True:
                line = f.readline()
                if not line:
                    return
                if in_data:
                    if line in (b".\r\n", b".\n"):
                        self.messages.append(b"".join(buffer))
                        buffer = []
                        in_data = False
                        f.write(b"250 OK\r\n")
                    else:
                        buffer.append(line)
                    f.flush()
                    continue
                cmd = line.strip().upper()
                if cmd.startswith((b"EHLO", b"HELO")):
                    f.write(b"250-localhost\r\n250-AUTH PLAIN\r\n250 OK\r\n")
                elif cmd.startswith(b"AUTH"):
                    f.write(b"235 OK\r\n")
                elif cmd == b"DATA":
                    in_data = True
                    f.write(b"354 go ahead\r\n")
                elif cmd == b"QUIT":
                    f.write(b"221 bye\r\n")
                    f.flush()
                    return
                else:
                    f.write(b"250 OK\r\n")
                f.flush()

    def latest_code(self, since: int = 0) -> str:
        """等下一封验证码邮件并取出 6 位数字"""
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if len(self.messages) > since:
                msg = email.message_from_bytes(
                    self.messages[-1], policy=policy.default
                )
                body = msg.get_body(preferencelist=("plain",)).get_content()
                found = re.search(r"验证码是\s*(\d{6})", body)
                if found:
                    return found.group(1)
            time.sleep(0.05)
        raise AssertionError("没等到验证码邮件")


@pytest.fixture
def smtp():
    return FakeSMTP()


@pytest.fixture
def b(backend, smtp):
    """配好假 SMTP、管理员已登录的后端"""
    inst = backend(
        db="two_factor.db",
        BOOTSTRAP_PASSWORD=PW,
        PUBLIC_BASE_URL="",
        SMTP_HOST="127.0.0.1",
        SMTP_PORT=str(smtp.port),
        SMTP_USER="noreply@example.com",
        SMTP_PASSWORD="smtp-secret",
        SMTP_SECURITY="none",
        TWO_FACTOR_MASTER_CODE=MASTER_CODE,
    )
    # 二次验证的设置接口不在初始化白名单里，得先把临时账号那一步走完
    assert inst.login(password=PW).status_code == 200
    r = inst.client.post(
        "/api/students",
        json={"student_no": ADMIN_NO, "name": "甲", "id_card": "110101200601010001"},
    )
    assert r.status_code == 200, r.text
    r = inst.client.post("/api/setup/finish", json={"admin_student_no": ADMIN_NO})
    assert r.status_code == 200, r.text
    inst.logout()
    assert inst.login(ADMIN_NO, LOGIN_PW).status_code == 200

    inst.run(
        "UPDATE users SET notify_email = ? WHERE student_no = ?",
        "admin@example.com",
        ADMIN_NO,
    )
    return inst


def _enable_email(b, smtp):
    """走完邮件二次验证的开启流程，返回恢复码"""
    before = len(smtp.messages)
    r = b.client.post("/api/auth/2fa/email/send", json={"password": LOGIN_PW})
    assert r.status_code == 200, r.text
    code = smtp.latest_code(before)
    r = b.client.post("/api/auth/2fa/email/confirm", json={"code": code})
    assert r.status_code == 200, r.text
    return r.json()["recovery_codes"]


def _enable_totp(b):
    r = b.client.post("/api/auth/2fa/totp/begin", json={"password": LOGIN_PW})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = b.client.post("/api/auth/2fa/totp/confirm", json={"code": code_at(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def _relogin(b):
    b.logout()
    return b.login(ADMIN_NO, LOGIN_PW)


# ---------- TOTP 纯函数 ----------


def test_totp_math():
    """RFC 6238 官方测试向量的后 6 位（SHA1、密钥是 ASCII 的 12345678901234567890）"""
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    for timestamp, expected in [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ]:
        assert code_for_step(secret, timestamp // STEP) == expected


def test_totp_window_and_replay():
    """当前步随时可用；上一步只在其起点后 45 秒内可用；用过的步不能重放"""
    secret = generate_secret()
    step = 1000
    t0 = step * STEP
    current = code_for_step(secret, step)
    previous = code_for_step(secret, step - 1)

    assert matches(secret, current, 0, at=t0) == step
    # 走到下一步的头 14.9 秒，上一步的码仍在 45 秒窗口内
    assert matches(secret, current, 0, at=t0 + STEP + 14.9) == step
    # 超过 45 秒就不认了
    assert matches(secret, current, 0, at=t0 + 45.1) is None
    # 上一步同理：从它的起点算 45 秒
    assert matches(secret, previous, 0, at=t0 + 14.9) == step - 1
    assert matches(secret, previous, 0, at=t0 + 15.1) is None
    # 同一个步再提交一次 = 重放，拒绝
    assert matches(secret, current, step, at=t0 + 1) is None
    # 空码、坏密钥、错码都只是不匹配，不抛异常
    assert matches(secret, "", 0, at=t0) is None
    assert matches("!!!", current, 0, at=t0) is None
    wrong = "000000" if current != "000000" else "111111"
    assert matches(secret, wrong, 0, at=t0) is None


# ---------- 万能验证码 ----------


def test_master_code_format():
    """只认恰好 6 位 ASCII 数字；其余一律当作没配"""
    from app.config import settings, two_factor_master_code

    original = settings.two_factor_master_code
    try:
        for bad in ("", "12345", "1234567", "12345a", "１２３４５６"):
            settings.two_factor_master_code = bad
            assert two_factor_master_code() == "", bad
        settings.two_factor_master_code = " 024681 "
        assert two_factor_master_code() == "024681"
    finally:
        settings.two_factor_master_code = original


def test_master_code_replaces_email(b, smtp):
    """邮箱方式：万能码能进门，响应与真码逐字一样（没有额外提示/恢复码字段）"""
    _enable_email(b, smtp)

    r = _relogin(b)
    assert r.json()["two_factor_required"] is True
    assert r.json()["method"] == "email"

    r = b.client.post("/api/auth/2fa/verify", json={"code": MASTER_CODE})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["student_no"] == ADMIN_NO
    assert "message" not in data
    assert "recovery_codes_left" not in data
    assert b.client.get("/api/auth/me").status_code == 200


def test_master_code_replaces_totp(b):
    """身份验证器方式：同一个万能码照样能进门，响应里也没有任何区别"""
    _enable_totp(b)

    _relogin(b)
    r = b.client.post("/api/auth/2fa/verify", json={"code": MASTER_CODE})
    assert r.status_code == 200, r.text
    assert r.json()["student_no"] == ADMIN_NO
    assert "message" not in r.json()
    assert b.client.get("/api/auth/me").status_code == 200


# ---------- 邮件方式 ----------


def test_email_flow(b, smtp):
    """开启 → 登出 → 密码登录只走一半 → 验证码通过后才真正登录"""
    codes = _enable_email(b, smtp)
    assert len(codes) == 10
    assert all(re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", c) for c in codes)

    status = b.client.get("/api/auth/2fa/status").json()
    assert status["enabled"] is True
    assert status["method"] == "email"
    assert status["email"] == "admin@example.com"
    assert status["recovery_codes_left"] == 10

    before = len(smtp.messages)
    r = _relogin(b)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["two_factor_required"] is True
    assert data["method"] == "email"
    assert data["email_sent"] is True
    # 密码只是第一步：这次还没有登录态
    assert b.client.get("/api/auth/me").status_code == 401

    r = b.client.post("/api/auth/2fa/verify", json={"code": "000000"})
    assert r.status_code == 400
    assert "还可以再试" in r.json()["detail"]

    r = b.client.post("/api/auth/2fa/verify", json={"code": smtp.latest_code(before)})
    assert r.status_code == 200, r.text
    assert r.json()["student_no"] == ADMIN_NO
    assert b.client.get("/api/auth/me").status_code == 200


def test_resend_cooldown_then_works(b, smtp):
    """重发有 60 秒冷却；冷却过后换新码，旧码作废"""
    _enable_email(b, smtp)

    before = len(smtp.messages)
    assert _relogin(b).json()["two_factor_required"] is True
    first_code = smtp.latest_code(before)

    r = b.client.post("/api/auth/2fa/resend")
    assert r.status_code == 400
    assert "秒后再重新发送" in r.json()["detail"]

    # 把「上次发送时间」拨回 61 秒前，省掉真等一分钟
    b.run(
        "UPDATE two_factor_challenges SET last_sent_at = datetime(last_sent_at, '-61 seconds')"
        " WHERE purpose = 'login' AND method = 'email'"
    )
    r = b.client.post("/api/auth/2fa/resend")
    assert r.status_code == 200, r.text
    new_code = smtp.latest_code(before + 1)

    # 旧码对应的挑战已经被新码覆盖
    if new_code != first_code:
        r = b.client.post("/api/auth/2fa/verify", json={"code": first_code})
        assert r.status_code == 400
    r = b.client.post("/api/auth/2fa/verify", json={"code": new_code})
    assert r.status_code == 200, r.text


# ---------- TOTP 方式 ----------


def test_totp_flow_recovery_and_disable(b):
    """TOTP 登录、恢复码只用一次、关闭后回到密码直登"""
    secret, codes = _enable_totp(b)
    assert len(codes) == 10

    r = _relogin(b)
    assert r.json()["two_factor_required"] is True
    assert r.json()["method"] == "totp"
    r = b.client.post("/api/auth/2fa/verify", json={"code": code_at(secret)})
    assert r.status_code == 200, r.text
    assert b.client.get("/api/auth/me").status_code == 200

    # 恢复码能进门，并告诉还剩几个
    r = _relogin(b)
    assert r.json()["two_factor_required"] is True
    r = b.client.post("/api/auth/2fa/verify", json={"code": codes[0]})
    assert r.status_code == 200, r.text
    assert r.json()["recovery_codes_left"] == 9
    assert "恢复码" in r.json()["message"]

    # 同一个恢复码不能再用
    _relogin(b)
    r = b.client.post("/api/auth/2fa/verify", json={"code": codes[0]})
    assert r.status_code == 400
    # 换一个恢复码可以；小写、无横杠也认
    r = b.client.post(
        "/api/auth/2fa/verify", json={"code": codes[1].replace("-", "").lower()}
    )
    assert r.status_code == 200, r.text

    # 关闭之后，密码登录直接成功
    r = b.client.post("/api/auth/2fa/disable", json={"password": LOGIN_PW})
    assert r.status_code == 200, r.text
    r = _relogin(b)
    assert r.status_code == 200
    assert "two_factor_required" not in r.json()


def test_wrong_code_limit(b):
    """一个挑战最多输错 5 次；用尽后会话里的引用也清掉"""
    secret, _ = _enable_totp(b)
    _relogin(b)
    wrong = "000000" if code_at(secret) != "000000" else "111111"
    last = None
    for _ in range(5):
        last = b.client.post("/api/auth/2fa/verify", json={"code": wrong})
        assert last.status_code == 400
    assert "次数过多" in last.json()["detail"]

    # 挑战已作废，再拿正确的码来也没用了，只能重新登录
    r = b.client.post("/api/auth/2fa/verify", json={"code": code_at(secret)})
    assert r.status_code == 400
    assert "登录状态已过期" in r.json()["detail"]


def test_admin_can_clear(b):
    """管理员清除后，账号回到密码直登，恢复码也没了"""
    _enable_totp(b)
    r = b.client.delete(f"/api/admin/users/{ADMIN_NO}/2fa")
    assert r.status_code == 200, r.text
    assert r.json()["was_enabled"] is True

    r = _relogin(b)
    assert r.status_code == 200
    assert "two_factor_required" not in r.json()
    assert b.client.get("/api/auth/2fa/status").json()["enabled"] is False
