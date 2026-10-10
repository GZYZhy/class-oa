"""全仓的 import 名字都得真的存在

**函数体内**的 import 是这类错的重灾区：`from .email_service import email_recipients,
email_enabled` 里那个用不上的 email_enabled（email_service 里根本没这个名字）只要
被调用就 ImportError —— 而调用它的 schedule_notify_service.tick 外面套着
try/except（那是故意的：一条发失败不能带走这一轮剩下的提醒），异常被吞掉只留一行
traceback 日志。结果是日程提醒从上线起一条都没推送出去过，代码却「看起来没问题」，
本机也不会红。

所以这里把每个模块的源码 AST 走一遍，逐条 import 解析名字 —— 不管是模块级还是
函数体内的，写错了当场红。

放在子进程里跑，并指向临时库：扫的是全 app 包，会 import app.main，
而它在 import 时就会建表 —— 不能在 pytest 进程里碰真库。
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 在子进程里跑的扫描脚本：import app 下所有模块，再 AST 扫各自的 import 语句
_SWEEP = """
import ast, importlib, pkgutil, sys
from pathlib import Path

import app

root = Path(app.__file__).parent
bad = []
checked = 0
for info in pkgutil.walk_packages([str(root)], prefix="app."):
    try:
        mod = importlib.import_module(info.name)
    except Exception as exc:
        bad.append(f"{info.name}: 整个模块 import 失败：{type(exc).__name__}: {exc}")
        continue
    src_path = getattr(mod, "__file__", None)
    if not src_path:
        continue
    tree = ast.parse(Path(src_path).read_text(encoding="utf-8"))
    # 相对 import 的基准：level=1 是本包，level=2 是上一级……（模块的 __package__）
    pkg_parts = (mod.__package__ or "").split(".") if mod.__package__ else []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
            target = ".".join(base + ([node.module] if node.module else []))
        else:
            target = node.module or ""
        checked += 1
        try:
            target_mod = importlib.import_module(target)
        except Exception as exc:
            bad.append(f"{info.name}:{node.lineno} from {target} import ..."
                       f" → 模块取不到：{type(exc).__name__}: {exc}")
            continue
        for alias in node.names:
            if alias.name != "*" and not hasattr(target_mod, alias.name):
                bad.append(f"{info.name}:{node.lineno} from {target} import {alias.name}"
                           f" → {target} 里没有这个名字")

if bad:
    print(f"扫了 {checked} 条 import，有 {len(bad)} 处有问题：")
    for line in bad:
        print("  -", line)
    sys.exit(1)
print(f"扫了 {checked} 条 import，名字全都能解析")
"""


def test_all_import_names_resolve(tmp_path):
    """每个 `from x import y` 的 y 都必须在 x 里真的存在（含函数体内的 import）"""
    result = subprocess.run(
        [sys.executable, "-c", _SWEEP],
        cwd=BACKEND_DIR,
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND_DIR),
            # 临时库 + 临时图片目录：扫全包会 import app.main，它 import 时就建表
            "DATABASE_URL": f"sqlite:///{tmp_path / 'imports.db'}",
            "PHOTO_DIR": str(tmp_path / "photos"),
            "BOOTSTRAP_PASSWORD": "",
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "有 import 的名字解析不了（函数体内的 import 要到真的调用时才炸，"
        "调用点外面往往还套着 try/except，表现成「功能悄悄不生效」）：\n"
        + result.stdout + result.stderr
    )
