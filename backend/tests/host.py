"""测试用的后端宿主：真起一个 uvicorn，供 pytest 通过 HTTP 驱动。

为什么非得起进程：`config.settings` 是模块级单例，`main.py` 在 **import 那一刻**
就建表、建账号、判初始化。同一个进程里既换不了库、也换不了配置，所以「空库 /
有库」「配了口令 / 没配」这类组合只能各起一个进程。

一般不用手跑，由 conftest.py 的 backend fixture 拉起：

    DATABASE_URL=sqlite:////tmp/x.db BOOTSTRAP_PASSWORD= TEST_PORT=8123 \
        python -m tests.host
"""

import os

import uvicorn

from app.main import app  # noqa: E402  —— 必须晚于环境变量就位才能 import
from app.services import login_guard  # noqa: E402

# 验证码不测：失败一次就要求验证码，会让「先故意错一次再正确登录」的场景全废
login_guard._CAPTCHA_THRESHOLD = 10 ** 6

uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.environ["TEST_PORT"]),
    log_level="warning",
)
