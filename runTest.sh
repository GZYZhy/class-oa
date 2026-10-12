#!/usr/bin/env bash
#
# 一键跑前后端两套回归测试，跑完只印一份简报。
#
#     ./runTest.sh
#
# 两套测试各自怎么跑（README「测试」一节）：
#   backend/tests    pytest 起真子进程后端，**每个用例一个全新临时库**，不碰 data/ 里的真实数据
#   frontend/tests   npm test，用 vite 的 SSR 管道真渲染 SFC，断言用户看得见的文案
#
# 两边**都跑完**才退出 —— 后端红了也要知道前端是不是也红了。
# 完整输出落在两个日志文件里（路径打在最下面），简报只留数字和失败清单；
# 想看某一条为什么红，去日志里搜用例名。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGDIR="$(mktemp -d -t class-oa-test)"
BACKLOG="${LOGDIR}/backend.log"
FRONTLOG="${LOGDIR}/frontend.log"

# 缺依赖就直说，别跑一半才报 ModuleNotFoundError
if ! python3 -c 'import pytest' 2>/dev/null; then
  echo "缺 pytest：pip3 install -r backend/requirements-dev.txt" >&2
  exit 1
fi
if [[ ! -d "${ROOT}/frontend/node_modules" ]]; then
  echo "缺前端依赖：cd frontend && npm install" >&2
  exit 1
fi

echo "▸ 后端 pytest（起真后端进程，这一套比前端慢得多）"
start=${SECONDS}
( cd "${ROOT}/backend" && python3 -m pytest tests -q ) >"${BACKLOG}" 2>&1
back_rc=$?
back_sec=$((SECONDS - start))

echo "▸ 前端 render.mjs"
start=${SECONDS}
( cd "${ROOT}/frontend" && npm test ) >"${FRONTLOG}" 2>&1
front_rc=$?
front_sec=$((SECONDS - start))

# 后端取 pytest 最后那行汇总（「264 passed in 132.07s」这种）；
# 前端只印了通过/失败的条数，断言总数得自己数 ✓
back_line="$(grep -oE '[0-9]+ (passed|failed|error)[^=]*in [0-9.]+s' "${BACKLOG}" | tail -1)"
front_pass="$(grep -c '✓' "${FRONTLOG}")"
front_line="$(grep -E '全部通过|失败 [0-9]+ 条' "${FRONTLOG}" | tail -1)"

echo
echo "==================== 测试简报 ===================="
if [[ ${back_rc} -eq 0 ]]; then
  printf '后端 pytest      ✓ 通过  %s（%s 秒）\n' "${back_line:-没读到汇总行}" "${back_sec}"
else
  printf '后端 pytest      ✗ 失败  %s（%s 秒）\n' "${back_line:-没读到汇总行}" "${back_sec}"
fi
if [[ ${front_rc} -eq 0 ]]; then
  printf '前端 render.mjs  ✓ 通过  %s，%s 条断言（%s 秒）\n' "${front_line:-没读到汇总行}" "${front_pass}" "${front_sec}"
else
  printf '前端 render.mjs  ✗ 失败  %s，通过 %s 条（%s 秒）\n' "${front_line:-没读到汇总行}" "${front_pass}" "${front_sec}"
fi

# 失败清单：后端认 pytest 的短摘要，前端认那一行 ✗
if [[ ${back_rc} -ne 0 ]]; then
  echo "--- 后端失败用例 ---"
  grep -E '^(FAILED|ERROR)' "${BACKLOG}" | head -20
fi
if [[ ${front_rc} -ne 0 ]]; then
  echo "--- 前端失败断言 ---"
  grep '✗' "${FRONTLOG}" | head -20
fi
# 一行汇总行都没读到，多半是压根没跑起来（缺依赖、语法错），把日志尾巴摊出来
if [[ ${back_rc} -ne 0 && -z "${back_line}" ]]; then
  echo "--- 后端日志结尾 ---"
  tail -15 "${BACKLOG}"
fi
if [[ ${front_rc} -ne 0 && -z "${front_line}" ]]; then
  echo "--- 前端日志结尾 ---"
  tail -15 "${FRONTLOG}"
fi

echo "--------------------------------------------------"
if [[ ${back_rc} -eq 0 && ${front_rc} -eq 0 ]]; then
  echo "两边全过。"
else
  echo "有红的，看上面的清单；完整输出："
fi
echo "  后端 ${BACKLOG}"
echo "  前端 ${FRONTLOG}"

[[ ${back_rc} -eq 0 && ${front_rc} -eq 0 ]]
