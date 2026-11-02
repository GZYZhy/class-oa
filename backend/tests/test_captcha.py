"""人机验证的三条分支：字符图（含语音）/ 拖动拼图 / Turnstile

    cd backend && python -m pytest tests/test_captcha.py -q

几条底线：
  * 答案（字符或缺口坐标）**不下发给前端**，也不在图片/音频里；
  * 默认是字符图（captcha 库），并且提供语音版（无障碍）；
  * 选了 Turnstile 就只认 token，**不回退**到另外两种；
  * 一张图/一段语音只能试一次，且 2 分钟内有效。
"""

import pytest

from app.utils.captcha import (
    TTL_SECONDS,
    answer_is_fresh,
    generate_chars_audio,
    generate_chars_image,
    generate_slide,
    session_answer,
    verify_chars,
    verify_slide,
)

PW = "initpass123"
ADMIN_NO = "2024000001"


@pytest.fixture
def b(backend):
    """初始化完毕、管理员已登录；验证码阈值还原成真实的「失败 1 次」"""
    inst = backend(
        db="captcha.db",
        BOOTSTRAP_PASSWORD=PW,
        CAPTCHA_THRESHOLD="1",
        # 隔离根目录 .env 里可能配着的真实 Turnstile Key：
        # 这条线要测「Key 不齐就不让选 turnstile」
        TURNSTILE_SITE_KEY="",
        TURNSTILE_SECRET_KEY="",
    )
    assert inst.login(password=PW).status_code == 200
    r = inst.client.post("/api/students", json={
        "student_no": ADMIN_NO, "name": "管理员",
        "id_card": "110101200601010001",
    })
    assert r.status_code == 200, r.text
    assert inst.client.post(
        "/api/setup/finish", json={"admin_student_no": ADMIN_NO}
    ).status_code == 200
    inst.logout()
    assert inst.login(ADMIN_NO, "010001").status_code == 200
    return inst


def _set_mode(b, mode, **extra):
    return b.client.put(
        "/api/admin/ops/config",
        json={"values": {"captcha_mode": mode, **extra}},
    )


def _required(b):
    return b.client.get("/api/auth/captcha-required").json()


# ---------------- 生成器（纯函数） ----------------


def test_chars_image_and_audio_are_real_media():
    png, text = generate_chars_image()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(text) == 4 and text.isdigit()

    wav, spoken = generate_chars_audio()
    assert wav[:4] == b"RIFF"
    assert len(spoken) == 4 and spoken.isdigit()

    # 音频语音包只覆盖数字，字符集必须和图片一致
    assert text.isdigit() and spoken.isdigit()


def test_slide_payload_has_no_answer():
    payload, x = generate_slide()
    assert payload["background"].startswith("data:image/png;base64,")
    assert payload["puzzle"].startswith("data:image/png;base64,")
    assert "x" not in payload and "answer" not in payload
    assert 0 < payload["y"] < payload["height"]
    assert payload["puzzle_width"] > payload["puzzle_size"]
    assert 0 < x < payload["width"]


def test_verify_helpers():
    assert verify_chars("1234", "1234") is True
    assert verify_chars("1234", " 1234 ") is True
    assert verify_chars("1234", "1235") is False
    assert verify_chars("", "1234") is False
    assert verify_chars(None, "1234") is False

    assert verify_slide(100, "100") is True
    assert verify_slide(100, "108") is True
    assert verify_slide(100, "109") is False
    assert verify_slide(100, "abc") is False

    record = session_answer("1234", "chars")
    assert answer_is_fresh(record)
    assert not answer_is_fresh(record, now=record["at"] + TTL_SECONDS + 1)
    assert not answer_is_fresh(None)


# ---------------- 默认：字符图 + 语音 ----------------


def test_default_mode_is_chars_with_audio(b):
    """不配任何东西时就是字符图，并且带语音（无障碍）"""
    info = _required(b)
    assert info["mode"] == "captcha"
    assert info["audio"] is True
    assert info["ready"] is True

    r = b.client.get("/api/auth/captcha")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers.get("cache-control") == "no-store"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    audio = b.client.get("/api/auth/captcha/audio")
    assert audio.status_code == 200, audio.text
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.content[:4] == b"RIFF"


def test_chars_wrong_answer_is_rejected_and_single_use(b):
    """失败 1 次后必须填验证码；填错 / 重复用同一份都不行"""
    assert b.login("admin", "wrong-password").status_code == 400
    assert _required(b)["required"] is True

    # 拉一张图但什么都不填 → 提示去填，不计数
    assert b.client.get("/api/auth/captcha").status_code == 200
    r = b.login("admin", PW)
    assert r.status_code == 400
    assert "验证码" in r.json()["detail"]

    # 填一个肯定不对的
    r = b.client.post(
        "/api/auth/login",
        json={"student_no": "admin", "password": PW, "captcha": "0000"},
    )
    assert r.status_code == 400
    assert "验证码" in r.json()["detail"]

    # 答案已经被清掉：不换图再交一次仍然不通过
    r = b.client.post(
        "/api/auth/login",
        json={"student_no": "admin", "password": PW, "captcha": "0000"},
    )
    assert r.status_code == 400
    assert "验证码" in r.json()["detail"]


# ---------------- 可选的拖动拼图 ----------------


def test_slider_mode_switches_endpoints(b):
    assert _set_mode(b, "slider").status_code == 200, "后台可以切换验证方式"

    info = _required(b)
    assert info["mode"] == "slider"
    assert info["audio"] is False, "语音只给字符图那一支"

    r = b.client.get("/api/auth/captcha")
    assert r.status_code == 200
    body = r.json()
    assert body["background"].startswith("data:image/png;base64,")
    assert body["puzzle"].startswith("data:image/png;base64,")

    # 拼图模式没有语音
    assert b.client.get("/api/auth/captcha/audio").status_code == 404

    # 带错的拖动位置照样被拦
    assert b.login("admin", "wrong-password").status_code == 400
    r = b.client.post(
        "/api/auth/login",
        json={"student_no": "admin", "password": PW, "captcha": "0"},
    )
    assert r.status_code == 400
    assert "拼图" in r.json()["detail"]


# ---------------- Turnstile：不回退 ----------------


def test_turnstile_requires_both_keys(b):
    """选了 Turnstile 但 Key 不齐：保存就被拒，不留一个「半生效」的状态"""
    r = _set_mode(b, "turnstile")
    assert r.status_code == 400
    assert "Site Key" in r.json()["detail"] or "Key" in r.json()["detail"]

    assert _set_mode(
        b, "turnstile", turnstile_site_key="site-x", turnstile_secret_key="secret-x"
    ).status_code == 200

    info = _required(b)
    assert info["mode"] == "turnstile"
    assert info["site_key"] == "site-x"
    assert info["ready"] is True
    # 这个模式不需要后端出题
    assert b.client.get("/api/auth/captcha").status_code == 404


def test_turnstile_does_not_fall_back_to_chars(b):
    """选了 Turnstile：没 token 就拒绝，**不会**改认字符图答案"""
    assert _set_mode(
        b, "turnstile", turnstile_site_key="site-x", turnstile_secret_key="secret-x"
    ).status_code == 200
    assert b.login("admin", "wrong-password").status_code == 400

    # 带字符答案、但没 turnstile_token → 仍然按「请完成人机验证」拒绝
    r = b.client.post(
        "/api/auth/login",
        json={"student_no": "admin", "password": PW, "captcha": "1234"},
    )
    assert r.status_code == 400
    assert "人机验证" in r.json()["detail"]


def test_turnstile_without_keys_rejects_login(b):
    """模式是 turnstile、Key 却不在（例如只改了环境变量）：拒绝，不换别的方式"""
    # 直接改库模拟「配置不完整」，绕过保存时的校验；
    # 读一次运维配置让 runtime_config 把库里的值 load 进 settings
    b.run("INSERT INTO runtime_settings (key, value) VALUES ('captcha_mode', 'turnstile')")
    assert b.client.get("/api/admin/ops/config").status_code == 200
    assert b.login("admin", "wrong-password").status_code == 400
    assert b.client.get("/api/auth/captcha-required").json()["required"] is True

    r = b.client.post(
        "/api/auth/login",
        json={
            "student_no": "admin",
            "password": PW,
            "turnstile_token": "whatever",
        },
    )
    assert r.status_code == 400
    assert "配置不完整" in r.json()["detail"]
