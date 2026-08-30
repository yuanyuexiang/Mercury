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
# 由 deploy.sh 首次部署自动生成（$(date +%F)）。
# 待补三项后重新部署即可完整启用（Actions 里 Run workflow，或 bash deploy.sh $TAG）：
#   TELEGRAM_BOT_TOKEN / OPERATOR_TELEGRAM_CHAT_ID / LLM_API_KEY

# Telegram（未配置时 bot 不收发消息，其余功能正常）
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)
OPERATOR_TELEGRAM_CHAT_ID=

# LLM（embedding 必须靠这里的 key；对话模型也可在后台「模型配置」里配）
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_CHAT_MODEL=gpt-4o-mini
LLM_CHAT_MODEL_FALLBACK=
LLM_EMBED_MODEL=text-embedding-3-small
SETTINGS_ENCRYPTION_KEY=${FERNET_KEY}
ALLOW_PRIVATE_LLM_BASE_URL=false
RAG_MIN_SIMILARITY=0.60
RAG_TOP_K=6
REPLY_DEADLINE_S=5

# 数据（容器内地址）
DATABASE_URL=postgresql+asyncpg://mercury:${PG_PASSWORD}@postgres:5432/mercury
REDIS_URL=redis://redis:6379/0

# 后台
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=${ADMIN_HASH}
JWT_SECRET=$(openssl rand -hex 32)
PUBLIC_BASE_URL=https://${DOMAIN}

# Google Sheets（可后补，配好后积压任务自动恢复）
GOOGLE_SERVICE_ACCOUNT_JSON=
LEADS_SPREADSHEET_ID=

# 运行
LOG_LEVEL=INFO
DATA_RETENTION_DAYS=180
STORAGE_DIR=var/storage

# 部署
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
  echo "    TELEGRAM_BOT_TOKEN / OPERATOR_TELEGRAM_CHAT_ID / LLM_API_KEY"
  echo "=================================================================="
fi

set -a
# shellcheck disable=SC1091
source .env
set +a
export IMAGE_TAG="$TAG"

echo "==> 部署 $TAG（当前运行：${PREV_TAG:-无记录}）"
docker compose -f compose.prod.yaml pull --quiet
docker compose -f compose.prod.yaml up -d --remove-orphans

echo "==> 健康检查 ${PUBLIC_BASE_URL}/health/ready"
if curl --fail --silent --retry 24 --retry-delay 5 --retry-all-errors \
    "${PUBLIC_BASE_URL}/health/ready" > /dev/null; then
  echo "$TAG" > "$PREV_FILE"
  echo "==> 部署成功：$TAG"
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
fi

echo "==> 健康检查失败！" >&2
if [ -n "$PREV_TAG" ] && [ "$PREV_TAG" != "$TAG" ]; then
  echo "==> 自动回滚到 $PREV_TAG" >&2
  IMAGE_TAG="$PREV_TAG" docker compose -f compose.prod.yaml up -d --remove-orphans
fi
exit 1
