"""测试装置：一个能反复起停的真后端 + 一个连着它的 HTTP 客户端。

每个用例、每次启动都是**全新进程 + 全新临时库**（原因见 tests/host.py 顶部），
所以用例之间不会互相串状态；同一个 db 名字重复起，就是在测「重启之后会怎样」。
"""

import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Backend:
    """一个活着的后端进程，以及连它的客户端与库文件"""

    def __init__(self, client: httpx.Client, proc: subprocess.Popen, db: Path):
        self.client = client
        self.db = db
        self._proc = proc

    # ---------- 常用动作 ----------

    def login(self, student_no="admin", password=""):
        return self.client.post(
            "/api/auth/login", json={"student_no": student_no, "password": password}
        )

    def logout(self):
        return self.client.post("/api/auth/logout")

    # ---------- 直接查库 ----------
    # 跨进程，ORM 用不上；好在 SQLite 就是一个文件，直接连过去看最实在

    def rows(self, sql: str, *params):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def run(self, sql: str, *params):
        con = sqlite3.connect(self.db)
        try:
            con.execute(sql, params)
            con.commit()
        finally:
            con.close()


@pytest.fixture
def backend(tmp_path):
    """backend(db="x.db", BOOTSTRAP_PASSWORD="...") -> Backend

    不传 BOOTSTRAP_PASSWORD 就是「功能关闭」那一档；同一个 db 名字再起一次，
    库还是那个库，用来测重启。
    """
    started = []

    def _start(db: str = "test.db", **env) -> Backend:
        port = _free_port()
        db_path = tmp_path / db
        proc = subprocess.Popen(
            [sys.executable, "-m", "tests.host"],
            cwd=BACKEND,
            env={
                **os.environ,
                "PYTHONPATH": str(BACKEND),
                "TEST_PORT": str(port),
                "DATABASE_URL": f"sqlite:///{db_path}",
                # 显式置空：不给的话会从仓库根或 backend/.env 里漏进来
                "BOOTSTRAP_PASSWORD": "",
                **env,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        started.append(proc)

        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10)
        for _ in range(150):
            if proc.poll() is not None:
                raise RuntimeError(f"后端没起来：\n{proc.stdout.read() if proc.stdout else ''}")
            try:
                if client.get("/api/health").status_code == 200:
                    return Backend(client, proc, db_path)
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("等后端就绪超时")

    yield _start

    for proc in started:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
