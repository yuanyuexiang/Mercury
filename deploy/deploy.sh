#!/usr/bin/env bash
# 服务器端部署脚本（技术方案 §17）：拉起指定 tag → 健康检查 → 失败自动回滚上一 tag。
# 用法：./deploy.sh [image_tag]   （默认 latest；deploy.yml 传 sha-*）
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-latest}"
PREV_FILE=".current_tag"
PREV_TAG="$(cat "$PREV_FILE" 2>/dev/null || echo "")"

# shellcheck disable=SC1091
set -a && source .env && set +a

echo "==> 部署 $TAG（当前运行：${PREV_TAG:-无记录}）"
IMAGE_TAG="$TAG" docker compose -f compose.prod.yaml pull --quiet
IMAGE_TAG="$TAG" docker compose -f compose.prod.yaml up -d --remove-orphans

echo "==> 健康检查 $PUBLIC_BASE_URL/health/ready"
if curl --fail --silent --retry 12 --retry-delay 5 --retry-all-errors \
    "$PUBLIC_BASE_URL/health/ready" > /dev/null; then
  echo "$TAG" > "$PREV_FILE"
  echo "==> 部署成功：$TAG"
  exit 0
fi

echo "==> 健康检查失败！" >&2
if [ -n "$PREV_TAG" ] && [ "$PREV_TAG" != "$TAG" ]; then
  echo "==> 自动回滚到 $PREV_TAG" >&2
  IMAGE_TAG="$PREV_TAG" docker compose -f compose.prod.yaml up -d --remove-orphans
fi
exit 1
