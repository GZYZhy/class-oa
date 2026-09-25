#!/usr/bin/env bash
#
# 构建生产镜像（后端 + 前端），打成 ghcr.io/gzyzhy/class-oa-* 的标签
#
# 用法：
#   ./scripts/build_images.sh                    # 只构建本机架构，版本号用今天日期
#   ./scripts/build_images.sh 2026-09-26         # 指定版本号
#   ./scripts/build_images.sh --push             # 构建双架构并推送到 GHCR
#   ./scripts/build_images.sh 2026-09-26 --push  # 指定版本号并推送
#
# 每个镜像打两个标签：版本号（可回溯、可回滚）和 latest（省事）。
# 不推送时镜像留在本地，docker-compose.yml 用 image: 直接引用；
# 推送后服务器 docker compose pull 就能拿到，不需要源码和构建链。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PREFIX="ghcr.io/gzyzhy/class-oa"

# 推送时构建的架构。
# 这台开发机是 Apple Silicon（arm64），只推本机架构的话，服务器（x86_64）拉下来
# 会直接报 no matching manifest 跑不起来 —— 所以 amd64 必须带上。
# 双架构 = arm64 走原生、amd64 走 QEMU 模拟，会比平时慢一些。
# 只给 amd64 服务器用的话可以加速：
#   PLATFORMS=linux/amd64 ./scripts/build_images.sh --push
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

PUSH=0
VERSION=""
for arg in "$@"; do
    case "$arg" in
        --push) PUSH=1 ;;
        -*)
            echo "错误：未知参数 ${arg}" >&2
            echo "用法：$0 [版本号] [--push]" >&2
            exit 1
            ;;
        *) VERSION="$arg" ;;
    esac
done
VERSION="${VERSION:-$(date +%Y-%m-%d)}"

if ! docker info >/dev/null 2>&1; then
    echo "错误：连不上 Docker 守护进程，请先启动 Docker Desktop（或 dockerd）" >&2
    exit 1
fi

# 推送前先确认登录过 GHCR。否则要等整个构建（可能要十几分钟）跑完，
# 才在最后一步 push 时报 401，白等一轮。
if [ "$PUSH" = 1 ] && ! grep -qs "ghcr.io" "${HOME}/.docker/config.json"; then
    cat >&2 <<'EOF'
错误：还没登录 GHCR。先执行下面这条，再重新运行本脚本：

    gh auth token | docker login ghcr.io -u <你的GitHub用户名> --password-stdin

（gh 的 token 需要带 write:packages 权限，`gh auth status` 可以看到）
EOF
    exit 1
fi

echo "==> 版本：${VERSION}"
if [ "$PUSH" = 1 ]; then
    echo "==> 模式：构建并推送（${PLATFORMS}）"
else
    echo "==> 模式：仅本地构建（本机架构，开发时最快）"
fi
echo

for service in backend frontend; do
    image="${IMAGE_PREFIX}-${service}"
    echo "==> 构建 ${image}:${VERSION}"
    if [ "$PUSH" = 1 ]; then
        # 多平台镜像没法 --load 进本地（docker 的限制），只能直接推走。
        # 想在本机跑就用不带 --push 的那条命令重新构建。
        docker buildx build \
            --platform "${PLATFORMS}" \
            -t "${image}:${VERSION}" \
            -t "${image}:latest" \
            --push \
            "${REPO_ROOT}/${service}"
    else
        docker build \
            -t "${image}:${VERSION}" \
            -t "${image}:latest" \
            "${REPO_ROOT}/${service}"
    fi
    echo
done

if [ "$PUSH" = 1 ]; then
    echo "==> 推送完成："
    echo "    ${IMAGE_PREFIX}-backend:${VERSION}"
    echo "    ${IMAGE_PREFIX}-frontend:${VERSION}"
    echo
    echo "（已带上 latest 标签。包是私有的，别的机器拉取前要先 docker login ghcr.io）"
else
    echo "==> 完成。本地镜像："
    docker images --filter "reference=${IMAGE_PREFIX}-*" --format '    {{.Repository}}:{{.Tag}}  {{.Size}}'
fi
echo
echo "启动：docker compose up -d"
echo "锁定版本：IMAGE_TAG=${VERSION} docker compose up -d"
