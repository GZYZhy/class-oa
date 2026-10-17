"""测试装置：一个能反复起停的真后端 + 一个连着它的 HTTP 客户端。

每个用例、每次启动都是**全新进程 + 全新临时库**（原因见 tests/host.py 顶部），
所以用例之间不会互相串状态；同一个 db 名字重复起，就是在测「重启之后会怎样」。
"""

import os
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

import httpx
import pytest

# 测试进程自身也得和后端子进程用同一个时区。用例里的 datetime.now() 拼的是
# 不带时区的时间串（和前端 el-date-picker 的 value-format 一样），后端子进程
# 按 TZ=Asia/Shanghai 解释它 —— 两边不一致时，在 UTC 的 CI 上「现在 + 2 小时」
# 会被后端算成已经过去，投票类用例集体报「截止时间已经过了」。
os.environ["TZ"] = "Asia/Shanghai"
if hasattr(time, "tzset"):
    time.tzset()

BACKEND = Path(__file__).resolve().parent.parent

# 让测试文件能直接 import app.*（比如 test_student_photos 要核对 PHOTO_FIELDS
# 与 PHOTO_TYPE_LABELS 的键集合是否一一对应）。
#
# 后端子进程那侧是 tests.host 自己设的 PYTHONPATH；pytest 进程这侧得在这里补 ——
# 不补的话，能 import 到什么完全取决于从哪个目录敲命令：`cd backend && pytest`
# 因为 CWD 进了 sys.path 而侥幸能过，从仓库根跑就是 ModuleNotFoundError: No module
# named 'app'。测试不该有这种隐含前提。
sys.path.insert(0, str(BACKEND))


def png_bytes() -> bytes:
    """一张 1×1 的真 PNG，给需要上传图片的用例共用

    后端眼下只认后缀和字节数、不解析图片，随便凑几个字节也能过；真图是为了
    将来加了图片校验时用例能安静地继续用，而不是莫名其妙地红掉。
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)   # 1×1、8 位、真彩色
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))   # 过滤字节 0 + 一个红点
        + chunk(b"IEND", b"")
    )


def _free_port() -> int:
    """问系统要一个空闲端口

    注意这是「问完就还回去」的用法：返回的端口到子进程真正绑上它是有一瞬空档的，
    别的进程（并行的另一个测试进程也算）可能抢先绑走 —— 此时子进程会当场退出，
    见 _start 里的重试。真要杜绝这个空档得把套接字传给子进程，为此改启动方式不值。
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _BootFailed(RuntimeError):
    """子进程在就绪之前就退了（端口被抢、依赖缺失、代码 import 不进去……）"""


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
        # 端口被别的进程抢走时子进程会立刻退出（见 _free_port）。这属于撞大运，
        # 换个端口重来就是；只有连着三次都起不来才认为后端真有问题，把子进程的
        # 输出抛出去。不重试的话，一次偶发撞车会报成「后端没起来」，让人去查代码
        for attempt in range(3):
            try:
                return _start_once(db, **env)
            except _BootFailed:
                if attempt == 2:
                    raise

    def _start_once(db: str, **env) -> Backend:
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
                # 照片也得另起一个目录：DATABASE_URL 只管库文件，照片走的是
                # config.BASE_DIR 下那个真实数据目录 —— 不隔离的话，测试上传的图
                # 会落在本机演示库的 photos 里，而且事后没人清得掉
                "PHOTO_DIR": str(tmp_path / "photos"),
                # 请假那条线的文件同理：辅助证明、班导师签字图副本都落在 LEAVE_DIR。
                # 接口测试一调「批准（带签字）」就会往里复制文件 —— 不隔离就写进
                # 本机演示库的真目录了
                "LEAVE_DIR": str(tmp_path / "leaves"),
                # 电动车同理：行驶证和经办班委签字图的副本都落在 EV_PASS_DIR，
                # 接口测试一调「批准（带签字）」或上传行驶证就会往里写文件
                "EV_PASS_DIR": str(tmp_path / "ev_passes"),
                # 证明的申请附件与成品 PDF 同理（这两个目录原先没吃环境变量，
                # 所以是后补的，见 certificates.py 里 ATTACH_DIR / RESULT_DIR 的注释）
                "CERT_ATTACH_DIR": str(tmp_path / "cert_attachments"),
                "CERT_RESULT_DIR": str(tmp_path / "cert_results"),
                # 公告 PDF 同理：上传接口会把文件写进 ANNOUNCEMENT_DIR，
                # 不隔离的话用例一上传就落进本机演示库的真目录
                "ANNOUNCEMENT_DIR": str(tmp_path / "announcements"),
                # 签到照片同理：学生一签到就写进 CHECKIN_DIR，测试必须另起目录
                "CHECKIN_DIR": str(tmp_path / "checkins"),
                # 固定成生产容器的时区：带时区的时间会换算成「本地墙上时间」，
                # CI 的 runner 是 UTC，不钉死的话同一份输入算出来的时刻和各人
                # 本机（Asia/Shanghai）不一样，测试就成了看机器的运气
                "TZ": "Asia/Shanghai",
                # 显式置空：不给的话会从仓库根或 backend/.env 里漏进来
                "BOOTSTRAP_PASSWORD": "",
                # 同理。配了公网地址后，所有「链接」类断言都会拿到生产域名，
                # 而不是这次临时起在 127.0.0.1 上的服务
                "PUBLIC_BASE_URL": "",
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
                raise _BootFailed(f"后端没起来：\n{proc.stdout.read() if proc.stdout else ''}")
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
