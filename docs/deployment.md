# 部署手册

前提：一台已运行 Traefik 的服务器（Docker + Compose）、一个解析到该服务器的域名、GitHub 仓库。
部署链路：push main → GitHub Actions 构建镜像推 GHCR → SSH 到服务器执行 `deploy.sh` → 健康检查（失败自动回滚上一版本）。

## 一、本地准备密钥（一次性）

```bash
openssl rand -hex 32        # → TELEGRAM_WEBHOOK_SECRET（≥32 字符）
openssl rand -hex 32        # → JWT_SECRET（≥32 字符）
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
                            # → SETTINGS_ENCRYPTION_KEY
uv run python -c "import bcrypt; print(bcrypt.hashpw(b'你的后台密码', bcrypt.gensalt()).decode())"
                            # → ADMIN_PASSWORD_HASH
```

## 二、服务器初始化（一次性）

```bash
sudo mkdir -p /opt/mercury && cd /opt/mercury
# 从仓库拷贝两个文件：
#   deploy/compose.prod.yaml → /opt/mercury/compose.prod.yaml
#   deploy/deploy.sh         → /opt/mercury/deploy.sh   （chmod +x）
docker network ls           # 确认既有 Traefik 的网络名 → TRAEFIK_NETWORK
```

创建 `/opt/mercury/.env`（参照仓库 `.env.example`），**生产必填**：

| 变量 | 说明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather 创建 |
| `TELEGRAM_WEBHOOK_SECRET` | 上面生成的 ≥32 字符 |
| `OPERATOR_TELEGRAM_CHAT_ID` | 人工提醒接收者（自己私聊 bot 后从 getUpdates 拿，或群 ID） |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_CHAT_MODEL` | **embedding 必须靠这里的 key**；对话模型也可稍后在后台配 |
| `LLM_EMBED_MODEL` | 默认 text-embedding-3-small |
| `SETTINGS_ENCRYPTION_KEY` | Fernet 主密钥 |
| `DATABASE_URL` | **`postgresql+asyncpg://mercury:<POSTGRES_PASSWORD>@postgres:5432/mercury`**（容器内主机名是 `postgres:5432`，不是 localhost:55432！） |
| `REDIS_URL` | `redis://redis:6379/0` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH` | 后台登录 |
| `JWT_SECRET` | ≥32 字符 |
| `PUBLIC_BASE_URL` | `https://你的域名` |
| `PUBLIC_HOST` | `你的域名`（不带协议） |
| `TRAEFIK_NETWORK` | 既有 Traefik 的 docker 网络名 |
| `GHCR_OWNER` | GitHub 用户/组织名 |
| `POSTGRES_PASSWORD` | 生产数据库密码 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` / `LEADS_SPREADSHEET_ID` | Sheets 同步（可后补，配好后积压任务自动恢复） |

注意：
- `PUBLIC_BASE_URL` 为 https 时，应用启动会**强制校验**以上安全项，弱配置直接拒绝启动（这是特性不是 bug）。
- `compose.prod.yaml` 中 Traefik labels 的 `entrypoints=websecure`、`certresolver=letsencrypt` 要与服务器既有 Traefik 配置一致，不一致就改 labels。
- **GHCR 镜像默认 private**：要么首次构建后在 GitHub Packages 页面把两个镜像设为 public，要么服务器上 `docker login ghcr.io -u <用户名>`（PAT 需 `read:packages`）。

## 三、GitHub 配置（一次性）

仓库 Settings → Secrets and variables → Actions，新增三个 secrets：

- `DEPLOY_HOST`：服务器 IP/域名
- `DEPLOY_USER`：SSH 用户（须能执行 docker）
- `DEPLOY_SSH_KEY`：SSH 私钥（对应公钥加入服务器 `~/.ssh/authorized_keys`）

## 四、首次发布

```bash
git push origin main    # 触发 Actions：构建 → 推 GHCR → SSH 部署 → 健康检查
```

在 Actions 页面看 Deploy workflow 全绿即部署成功；`https://你的域名/health/ready` 应返回 `{"status":"ok"}`。

## 五、部署后一次性动作

1. **注册 Telegram webhook**（本地执行，环境变量用生产值）：
   ```bash
   TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... PUBLIC_BASE_URL=https://你的域名 \
     uv run python scripts/set_webhook.py
   ```
2. 打开 `https://你的域名/login` 登录后台。
3. 「知识库」上传产品文档，等状态变 `active`。
4. 「模型配置」新增供应商 → 测试 → 激活（或直接用 .env 里的兜底配置）。
5. Telegram 里给 bot 发消息，走一遍演示剧本（私有化部署 → HubSpot → 50 人价格 → 约 Demo），后台应出现 high 线索、Google Sheet 出现一行。

## 六、日常运维

| 操作 | 方法 |
|---|---|
| 发新版 | 合并/推送到 main，自动发布 |
| 回滚 | Actions → Deploy → Run workflow → `image_tag` 填历史 `sha-*` |
| 看日志 | 服务器 `docker compose -f compose.prod.yaml logs -f api worker` |
| 手动部署 | 服务器 `./deploy.sh sha-xxxxxxx`（健康检查失败自动回滚） |
| 备份 | backup 服务每日 `pg_dump` 到 `backups` volume，保留 14 份 |
| 换模型/换 key | 后台「模型配置」，无需重启 |
| 删用户数据 | `DELETE /api/users/by-telegram/{id}`（需登录 + CSRF 头） |

## 附：Telegram 对接细节

### 1. 创建 Bot（拿 TELEGRAM_BOT_TOKEN）

1. Telegram 里搜索 **@BotFather** → 发送 `/newbot`；
2. 依次输入 bot 显示名称、username（必须以 `bot` 结尾，如 `nimbus_support_bot`）；
3. BotFather 返回的 `123456:ABC-xxx` 就是 `TELEGRAM_BOT_TOKEN`。

建议顺手在 BotFather 里配置命令菜单（`/setcommands`）：

```text
start - 开始对话
human - 转人工客服
reset - 重新开始会话
```

### 2. 获取 OPERATOR_TELEGRAM_CHAT_ID（人工提醒发到哪）

Telegram 规定 bot 不能主动私聊没找过它的人，所以必须先发起对话：

- **私聊接收**：用你自己的账号给 bot 发任意一条消息，然后执行：
  ```bash
  curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep -A2 '"chat"'
  ```
  结果里 `message.chat.id`（正数）就是你的 chat ID。
- **群接收**（推荐，团队都能看到）：建一个群、把 bot 拉进去、在群里发一条 @bot 的消息，同样用 getUpdates 读 `chat.id`（群 ID 是**负数**，照抄即可）。

### 3. 注册 Webhook

前提：服务已部署且 https 可达（Telegram 只接受 https）。`.env` 配好
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` / `PUBLIC_BASE_URL` 后：

```bash
uv run python scripts/set_webhook.py
```

脚本做三件事：`setWebhook` 指向 `https://域名/webhooks/telegram/<secret>`、设置
`secret_token`（请求头二次校验）、限定 `allowed_updates=["message"]`。

验证是否生效：

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo" | python3 -m json.tool
# 看 url 是否正确、pending_update_count 是否在消化、last_error_message 是否为空
```

### 4. 本地开发联调（无公网服务器时）

- **纯本地**：不配 `TELEGRAM_BOT_TOKEN`，系统自动用 LoggingSender 替身（回复打日志不发网络）；
  用 curl 模拟 Telegram 推送即可全链路测试（payload 结构见 `tests/conftest.py` 的 `tg_update`）。
- **真机联调**：`ngrok http 8000` 或 cloudflared tunnel 拿到临时 https 地址 →
  `PUBLIC_BASE_URL` 设为该地址 → 跑 `set_webhook.py` → 手机上真实对话。

### 5. 常见问题

| 现象 | 排查 |
|---|---|
| bot 完全不回复 | `getWebhookInfo` 看 `last_error_message`：404 = Traefik 路由 `/webhooks` 没到 api 或 secret 不一致；SSL 错误 = 证书未签好 |
| webhook 显示正常但没反应 | 看 worker 日志（消息处理在 worker，不在 api）：`docker compose -f compose.prod.yaml logs -f worker` |
| 回复"系统暂未就绪" | LLM 未配置：`.env` 填 `LLM_API_KEY`/`LLM_CHAT_MODEL`，或后台「模型配置」激活供应商 |
| 收不到人工提醒 | 运营者/群从未给 bot 发过消息，或 `OPERATOR_TELEGRAM_CHAT_ID` 填错（群是负数） |
| 之前用过轮询 | `setWebhook` 会自动替换轮询模式，无需手动 `deleteWebhook` |
