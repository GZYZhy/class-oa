#!/usr/bin/env bash
#
# 构建生产镜像（后端 + 前端），打成 gzyzhy/class-oa-* 的标签
#
# 用法：
#   ./scripts/build_images.sh            # 版本号用今天日期，如 2026-09-25
#   ./scripts/build_images.sh v1.2.0     # 指定版本号
#
# 每个镜像打两个标签：版本号（可回溯、可回滚）和 latest（省事）。
# 构建完镜像就躺在本地，docker-compose.yml 用 image: 直接引用，不再走 compose 的 build
# —— 这样服务器上只要拿到镜像就能跑，不需要源码里的构建链。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_PREFIX="gzyzhy/class-oa"
VERSION="${1:-$(date +%Y-%m-%d)}"

if ! docker info >/dev/null 2>&1; then
    echo "错误：连不上 Docker 守护进程，请先启动 Docker Desktop（或 dockerd）" >&2
    exit 1
fi

echo "==> 构建版本：${VERSION}"
echo

for service in backend frontend; do
    image="${IMAGE_PREFIX}-${service}"
    echo "==> 构建 ${image}:${VERSION}"
    docker build \
        -t "${image}:${VERSION}" \
        -t "${image}:latest" \
        "${REPO_ROOT}/${service}"
    echo
done

echo "==> 完成。本地镜像："
docker images --filter "reference=${IMAGE_PREFIX}-*" --format '    {{.Repository}}:{{.Tag}}  {{.Size}}'
echo
echo "启动：docker compose up -d"
echo "锁定版本：IMAGE_TAG=${VERSION} docker compose up -d"
