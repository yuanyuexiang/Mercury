#!/usr/bin/env bash
# 服务器端部署脚本（由 deploy.yml 经 SSH 调用；也可手动 bash deploy.sh <tag>）。
# 首次运行自动生成 .env（随机密钥，管理员密码只打印一次）→ 拉起 → 健康检查
# （失败自动回滚上一 tag）→ 自动注册 Telegram webhook（token 已配置时）。
set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-latest}"
GHCR_OWNER="${GHCR_OWNER:?需要 GHCR_OWNER 环境变量}"
DOMAIN="${DOMAIN:?需要 DOMAIN 环境变量}"
TRAEFIK_NETWORK="${TRAEFIK_NETWORK:-matrix-network}"
TRAEFIK_CERTRESOLVER="${TRAEFIK_CERTRESOLVER:-letsencrypt}"
APP_IMAGE="ghcr.io/${GHCR_OWNER}/mercury-app:${TAG}"
PREV_FILE=".current_tag"
PREV_TAG="$(cat "$PREV_FILE" 2>/dev/null || echo "")"

docker pull -q "$APP_IMAGE"

if [ ! -f .env ]; then
  echo "==> 首次部署：自动生成 .env（随机密钥）"
  ADMIN_PASSWORD="$(openssl rand -hex 8)"
  ADMIN_HASH="$(docker run --rm "$APP_IMAGE" python -c "import bcrypt;print(bcrypt.hashpw('${ADMIN_PASSWORD}'.encode(),bcrypt.gensalt()).decode())")"
  FERNET_KEY="$(docker run --rm "$APP_IMAGE" python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")"
  PG_PASSWORD="$(openssl rand -hex 16)"
  cat > .env <<EOF
# 由 deploy.sh 首次部署自动生成（$(date +%F)）。只保留密钥与基础设施配置；
# LLM 在后台「模型配置」页配置；调优参数走代码默认值（packages/domain/config.py）。
# 待补两项后重新部署即可启用 bot（Actions 里 Run workflow）：
#   TELEGRAM_BOT_TOKEN / OPERATOR_TELEGRAM_CHAT_ID

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)
OPERATOR_TELEGRAM_CHAT_ID=

# 数据（容器内地址）
DATABASE_URL=postgresql+asyncpg://mercury:${PG_PASSWORD}@mercury-db:5432/mercury
REDIS_URL=redis://mercury-redis:6379/0

# 后台（hash 单引号：防 compose dotenv 对 \$ 做插值）
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH='${ADMIN_HASH}'
JWT_SECRET=$(openssl rand -hex 32)
PUBLIC_BASE_URL=https://${DOMAIN}
SETTINGS_ENCRYPTION_KEY=${FERNET_KEY}

# 可选：Sheets 同步（GOOGLE_SERVICE_ACCOUNT_JSON / LEADS_SPREADSHEET_ID）
# 可选：LLM env 兜底（LLM_API_KEY / LLM_CHAT_MODEL 等，推荐用后台配置）

# 部署（compose.prod.yaml 插值用）
TRAEFIK_NETWORK=${TRAEFIK_NETWORK}
TRAEFIK_CERTRESOLVER=${TRAEFIK_CERTRESOLVER}
PUBLIC_HOST=${DOMAIN}
GHCR_OWNER=${GHCR_OWNER}
POSTGRES_PASSWORD=${PG_PASSWORD}
EOF
  chmod 600 .env
  echo "=================================================================="
  echo "  后台地址：https://${DOMAIN}/login    用户名：admin"
  echo "  初始密码：${ADMIN_PASSWORD}"
  echo "  ⚠️ 只显示这一次，立即保存！"
  echo "  待补配置（编辑 ~/mercury/.env 后重新部署）："
  echo "    TELEGRAM_BOT_TOKEN / OPERATOR_TELEGRAM_CHAT_ID"
  echo "  LLM 直接在后台「模型配置」页配置即可（无需改 .env）"
  echo "=================================================================="
fi

# 绝不 source .env：bcrypt hash 以 $2b$ 开头，bash 会当位置参数展开（set -u 下直接退出）。
# compose 用 --env-file 自行解析（dotenv 不做 shell 展开）；脚本只提取自己要用的值。
env_get() { grep -E "^${1}=" .env | head -1 | cut -d'=' -f2-; }
PUBLIC_BASE_URL="$(env_get PUBLIC_BASE_URL)"
TELEGRAM_BOT_TOKEN="$(env_get TELEGRAM_BOT_TOKEN)"
TELEGRAM_WEBHOOK_SECRET="$(env_get TELEGRAM_WEBHOOK_SECRET)"
export IMAGE_TAG="$TAG"
COMPOSE=(docker compose --env-file .env -f compose.prod.yaml)

echo "==> 部署 $TAG（当前运行：${PREV_TAG:-无记录}）"
"${COMPOSE[@]}" pull --quiet
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> 健康检查①：容器内应用就绪（不经 Traefik/DNS，只验应用本体）"
READY=0
for _ in $(seq 1 18); do
  if "${COMPOSE[@]}" exec -T api python -c \
      "import urllib.request as u,sys;sys.exit(0 if u.urlopen('http://localhost:8000/health/ready',timeout=5).status==200 else 1)" \
      2>/dev/null; then
    READY=1
    break
  fi
  sleep 5
done

if [ "$READY" != "1" ]; then
  echo "==> ❌ 应用未就绪，自动诊断：" >&2
  echo "---- 容器状态 ----" >&2
  "${COMPOSE[@]}" ps >&2 || true
  echo "---- api 最近日志 ----" >&2
  "${COMPOSE[@]}" logs --tail 15 api 2>&1 | tail -30 >&2 || true
  echo "---- api 容器内实际连接串（脱敏） ----" >&2
  "${COMPOSE[@]}" exec -T api python -c \
    "import os,re;print('DATABASE_URL =',re.sub(r':[^:@/]+@',':***@',os.environ.get('DATABASE_URL','(未设置)')));print('REDIS_URL    =',os.environ.get('REDIS_URL','(未设置)'))" >&2 || true
  if [ -n "$PREV_TAG" ] && [ "$PREV_TAG" != "$TAG" ]; then
    echo "==> 自动回滚到 $PREV_TAG" >&2
    IMAGE_TAG="$PREV_TAG" "${COMPOSE[@]}" up -d --remove-orphans
  fi
  exit 1
fi
echo "$TAG" > "$PREV_FILE"  # 应用本体健康即记录：.current_tag = 最后一个可用版本
echo "==> 应用就绪：$TAG"

echo "==> 健康检查②：公网入口 ${PUBLIC_BASE_URL}/health/ready"
if curl --fail --silent --retry 12 --retry-delay 5 --retry-all-errors \
    "${PUBLIC_BASE_URL}/health/ready" > /dev/null; then
  echo "==> 公网可达，部署成功：$TAG"
else
  echo "==> ⚠️ 应用已就绪但公网访问失败——问题在 Traefik 路由/证书/DNS 层，回滚无益，不回滚。" >&2
  echo "==> 排查：docker logs <traefik 容器>；确认 DNS 解析与 certresolver 配置。" >&2
  exit 1
fi

if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
  if curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
      -d "url=${PUBLIC_BASE_URL}/webhooks/telegram/${TELEGRAM_WEBHOOK_SECRET}" \
      -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \
      -d 'allowed_updates=["message"]' > /dev/null; then
    echo "==> Telegram webhook 已自动注册"
  else
    echo "==> ⚠️ webhook 注册失败，请检查 TELEGRAM_BOT_TOKEN" >&2
  fi
else
  echo "==> 提示：TELEGRAM_BOT_TOKEN 未配置，跳过 webhook（补配后重新部署即自动注册）"
fi
exit 0
