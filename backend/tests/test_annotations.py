"""注解里用到的名字，必须在模块级可见

本机（3.14）跑测试是**发现不了**这件事的：PEP 649 之后函数注解不再在 def 时
求值，`def f() -> Optional[tuple[int, ICalToken]]` 里那个只在函数体内 import 的
名字永远不会被检查。而容器里是 3.12，注解当场求值 —— 1.10.0 就是这么炸的：
本地 89 个测试全绿，线上 `NameError: name 'ICalToken' is not defined`，
整个后端 import 阶段崩掉、起不来。

这里把每个模块、每个函数/类的注解显式求值一遍（get_annotations(eval_str=True)
在 3.14 上也会真的求值），把 3.12 的即时求值行为搬进测试。

放在子进程里跑，并指向临时库：扫的是全 app 包，会 import app.main，
而它在 import 时就会建表 —— 不能在 pytest 进程里碰真库。
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 在子进程里跑的扫描脚本：import app 下所有模块，逐个求值注解
_SWEEP = """
import importlib, inspect, pkgutil, sys
from pathlib import Path

import app

root = Path(app.__file__).parent
bad = []
count = 0
for info in pkgutil.walk_packages([str(root)], prefix="app."):
    try:
        mod = importlib.import_module(info.name)
    except Exception as exc:
        bad.append(f"{info.name}: 整个模块 import 失败：{type(exc).__name__}: {exc}")
        continue
    for obj_name, obj in vars(mod).items():
        # 只看这个模块自己定义的东西，import 进来的不算
        if getattr(obj, "__module__", None) != info.name:
            continue
        if not (inspect.isfunction(obj) or inspect.isclass(obj)):
            continue
        count += 1
        try:
            inspect.get_annotations(obj, eval_str=True)
        except Exception as exc:
            bad.append(f"{info.name}.{obj_name}: {type(exc).__name__}: {exc}")

if bad:
    print(f"扫了 {count} 个函数/类，有 {len(bad)} 处注解求不出来：")
    for line in bad:
        print("  -", line)
    sys.exit(1)
print(f"扫了 {count} 个函数/类，注解全都能求值")
"""


def test_all_annotations_are_evaluatable(tmp_path):
    """所有模块级函数/类的注解都要能在「def 时立即求值」的语义下求出来"""
    result = subprocess.run(
        [sys.executable, "-c", _SWEEP],
        cwd=BACKEND_DIR,
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND_DIR),
            # 临时库 + 临时图片目录：扫全包会 import app.main，它 import 时就建表
            "DATABASE_URL": f"sqlite:///{tmp_path / 'annotations.db'}",
            "PHOTO_DIR": str(tmp_path / "photos"),
            # 别让它顺手把资料下载条目导进这个临时库，跑得更干净
            "BOOTSTRAP_PASSWORD": "",
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "有注解在「def 时求值」的语义下求不出来（写注解时用到的名字必须模块级可见，"
        "不能只在函数体内 import）：\n" + result.stdout + result.stderr
    )
