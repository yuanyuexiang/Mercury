# 部署手册（极简版）

目标环境已内置在 `cd.yml` 顶部 env：域名 `mercury.asksquirrel.ai`、Traefik 网络
`matrix-network`、证书 resolver `cloudflare`。换环境改那四行即可。

部署链路：push（main/master）→ Actions 构建推 GHCR → **自动** scp 部署文件到服务器
`~/mercury/` → **自动**首次生成 .env（随机密钥）→ 拉起 → 健康检查（失败自动回滚）
→ **自动**注册 Telegram webhook。服务器上无需任何预置。

## 一、前置（已完成的打勾）

- [x] DNS：`mercury.asksquirrel.ai` A → 54.70.201.189
- [x] GitHub Repository Variables：`SSH_HOST` / `SSH_USER` / `SSH_PRIVATE_KEY`
      （⚠️ 测试期从简放 Variables；上生产前迁 Secrets 并换私钥——Variables 明文可见）
- [ ] push 代码到 main 或 master

## 二、首次发布

```bash
git push
```

看 Actions → Deploy 日志：首次部署会打印**后台初始密码（只显示一次，立即保存）**。
完成后验证：`curl https://mercury.asksquirrel.ai/health/ready` → `{"status":"ok"}`，
后台 `https://mercury.asksquirrel.ai/login`（用户名 admin）。

## 三、后台完成全部配置（无需再碰 .env）

登录后台，两个页面配完即可开门迎客：

1. **「系统设置」→ Telegram 接入**：页面本身就是三步向导——① 按提示到 @BotFather
   创建机器人；② 粘贴 Token「保存并验证」（自动校验 + 注册 webhook）；③ 用自己的
   Telegram 给机器人发一句话 → 点「检测最近联系人」→ 从列表里点选接收通知的人/群
   （**无需命令行查 Chat ID**）→「发送测试通知」确认全链路。品牌/语气也在这页配。
2. **「模型配置」**：新增供应商（base_url / key / 对话模型 / embedding 模型）→
   测试 → 激活，即时生效。

Token 以加密形式存库（主密钥在服务器 .env 的 `SETTINGS_ENCRYPTION_KEY`），改任何
配置都**不需要重启或重新部署**。`.env` 里的 `TELEGRAM_BOT_TOKEN` /
`OPERATOR_TELEGRAM_CHAT_ID` 仍可作为兜底（后台未配置时生效），但推荐统一走后台。

## 四、日常运维

| 操作 | 方法 |
|---|---|
| 发新版 | push 到 main/master，自动发布 |
| 回滚 | Actions → Deploy → Run workflow → `image_tag` 填历史 `sha-*` |
| 看日志 | 服务器 `cd ~/mercury && docker compose -f compose.prod.yaml logs -f api worker` |
| 备份 | backup 服务每日 `pg_dump`，保留 14 份 |
| 换模型/换 key | 后台「模型配置」，无需重启 |
| 换 bot / 改通知人 / 改品牌 | 后台「系统设置」，保存自动验证并注册 webhook，无需重启 |
| 改域名/环境 | 改 `cd.yml` 顶部 env 四行 + 服务器 `.env` 对应项 |
| 后台改密码 | 生成新 hash 替换 `.env` 的 `ADMIN_PASSWORD_HASH` 后重新部署 |
| 删用户数据 | `DELETE /api/users/by-telegram/{id}`（需登录 + CSRF 头） |

上传知识库文档、配置/切换模型供应商都在后台页面完成（「知识库」/「模型配置」）。

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

**正常情况不需要手动查**：后台「系统设置」的「检测最近联系人」会从 webhook 流量里
自动列出候选（前提是接收人先给 bot 发过一句话）。以下手动方式仅用于排障或纯 .env 流程。

Telegram 规定 bot 不能主动私聊没找过它的人，所以必须先发起对话：

- **私聊接收**：用你自己的账号给 bot 发任意一条消息，然后执行：
  ```bash
  curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep -A2 '"chat"'
  ```
  结果里 `message.chat.id`（正数）就是你的 chat ID。
- **群接收**（推荐，团队都能看到）：建一个群、把 bot 拉进去、在群里发一条 @bot 的消息，同样用 getUpdates 读 `chat.id`（群 ID 是**负数**，照抄即可）。

### 3. 注册 Webhook

**正常情况不需要手动做**：后台「系统设置」保存 Bot Token 时自动注册（要求服务已
https 可达）。以下手动方式仅用于排障或纯 .env 流程：

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

## 附二：真实流量调优实录（2026-09-01 首个真实用户排查沉淀）

首次接真实流量暴露的三个问题及修法——**每个新客户实例上线时都按此检查**：

| 问题 | 症状 | 根因 | 修法 |
|---|---|---|---|
| 大 ID 卡死 | 所有消息卡 `processing`，worker 日志 `value out of int32 range` | 现代 Telegram user/chat id 超出 int32（如 76 亿），顺序守卫按 INTEGER 比较 | 已修（repositories.py 按 BIGINT 处理），升级镜像即可 |
| 知识库永远拒答 | 文档已启用仍回"无法从官方资料确认"，英文提问尤甚 | 相似度阈值 0.60 按 OpenAI embedding 调，Qwen3-Embedding 分布整体偏低，跨语言更低 | `.env` 设 `RAG_MIN_SIMILARITY=0.45`（换 embedding 模型后用容器内诊断脚本实测 top 分数再定）|
| 生成必超时 | 检索命中但 `llm_chat_attempt_failed purpose=rag` → TimeoutError | **对话槽误选深度思考型模型**（glm-4.7 等），出话十几秒起步 | 对话模型必须选 flash/turbo 级快速模型（glm-4.7-flash 等）；思考型模型不适用客服场景 |

配套调整：`REPLY_DEADLINE_S=15` + `TRIAGE_TIMEOUT_S=5`（DeepSeek-V3 出一段 triage JSON 要 2–5 秒，默认 2s 上限会让意图识别每次超时降级——症状：问答正常但**永远不生成线索**，日志持续 `llm_chat_attempt_failed purpose=triage`）；`RAG_TOP_K=10`（不同 embedding 模型排序口味不同，top-6 可能挤掉关键块——实测 Qwen3-Embedding 把定价文档的说明块排在实际价格块之前，导致模型守规矩拒答）。embedding 闲置后首调有数秒冷启动属正常。

**模型选型铁律（2026-09 实测）**：对话槽只能用**非思考型快速模型**——智谱 4.7/5.x 全系（含 flash 后缀）默认深度思考，出话 10 秒+，必超时；可用：glm-4-flash（免费、偏弱）、SiliconFlow 的 deepseek-ai/DeepSeek-V3（推荐）。换 embedding 模型后要连着验证：阈值（诊断脚本看 top 分数）+ top_k（确认关键块入围）。

**手动改 .env 后的安全重启**：deploy.sh 会把当前版本写进 `.env` 的 `IMAGE_TAG`，因此改配置后直接
`docker compose --env-file .env -f compose.prod.yaml up -d --force-recreate api worker` 即可。
⚠ 若 `.env` 里没有 `IMAGE_TAG`（旧版 deploy.sh 部署的），先补 `IMAGE_TAG=$(cat .current_tag)`，
否则 compose 会回退到本地陈旧的 `:latest` 镜像——症状是重启后"修过的 bug 又回来了"。

**容器内检索诊断**（打印 top-6 相似度与生成结果，定位拒答原因）：
```bash
docker compose -f compose.prod.yaml exec -T api python - <<'PYEOF'
import asyncio
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from domain.config import get_settings
from llm.provider_config import ProviderSource, DynamicEmbedder
from llm.rag import retrieve

async def main():
    s = get_settings()
    print("阈值 =", s.rag_min_similarity, "| 预算 =", s.reply_deadline_s)
    engine = create_async_engine(s.database_url)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    r = aioredis.from_url(s.redis_url)
    emb = DynamicEmbedder(ProviderSource(sf, r, s), s)
    for q in ["你们怎么收费", "How much does it cost"]:
        print("=== 查询:", q)
        async with sf() as session:
            for c in await retrieve(session, emb, q, 6, 0.0):
                print(f"  {c.similarity:.3f}  {c.document_title}")
    await engine.dispose()
    await r.aclose()

asyncio.run(main())
PYEOF
```
