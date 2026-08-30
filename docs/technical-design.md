# 技术实现方案

Telegram AI 客服与询盘转化系统 — 实现级设计 v1.4（2026-08-30，三轮外部评审修订 + §20 产品化定制路线：租户边界预留与配置面定案）

- 上游文档：[Telegram-AI-Lead-System-MVP.md](./Telegram-AI-Lead-System-MVP.md)（需求与边界以它为准；其 §6 技术建议已被本文档替代）
- 本文档用途：指导代码生成。所有"二选一"已在此定案，代码生成阶段不再做架构决策。
- 日期：2026-08-29

---

## 1. 技术决策清单（定案）

MVP 文档留了若干开放选项，这里全部定下来，附理由：

| 决策点 | 定案 | 理由 |
|---|---|---|
| Telegram 库 | **aiogram 3.x**（仅用其 Bot API client + 类型，不用其轮询/路由框架） | 全异步、类型完整；webhook 由 FastAPI 接，不需要 aiogram 的 Dispatcher |
| 编排框架 | **纯 Python 显式管线，不用 LangGraph** | 编排是确定性决策树（状态检查→风险→意图→RAG），显式代码比图框架更易测试、易生成正确代码；LangChain 仅保留 `langchain-text-splitters` 做切分 |
| 结构化输出 | **OpenAI structured outputs（json_schema）+ Pydantic 双重校验** | 字段提取、意图/风险分类都走这条路，失败可降级重试一次 |
| ORM / 迁移 | **SQLAlchemy 2.0 async + asyncpg + Alembic** | 生态标准 |
| 任务队列 | **arq**（Redis 之上的 asyncio 队列） | 轻量、asyncio 原生，与 FastAPI 同一并发模型；Celery 对本规模过重 |
| 消息处理位置 | **api 只接收入库入队，LLM 管线全部在 worker 执行** | webhook 必须毫秒级返回 200，避免 Telegram 重推；worker 崩溃可重试，满足"消息处理可追踪率 100%" |
| CRM 首选 | **Google Sheets（gspread + Service Account）** | 零部署依赖，最快出首个演示；通过 `LeadSyncPort` 接口隔离，Twenty/HubSpot 后续可插 |
| Embedding | **OpenAI 兼容接口，默认 `text-embedding-3-small`（1536 维）** | 维度写进 migration，换维度需重建索引，配置中显式声明 |
| PDF / 网页解析 | **pypdf**；网页用 **trafilatura** | 够用且轻 |
| 后台认证 | **单管理员，env 配置凭据（密码 bcrypt hash），JWT 放 httpOnly cookie，同域部署** | MVP 无多用户需求；Traefik 下 web 与 api 同域名（`/api` 前缀），cookie 最简单也最安全 |
| 人工提醒渠道 | **Telegram 通知**（发给 `OPERATOR_TELEGRAM_CHAT_ID` 指定的运营者私聊/群） | P0 内零额外依赖 |
| 模型配置方式 | **后台可配多供应商（DB 加密存储）+ env 兜底**，对话与 embedding 均可后台配 | 交付客户后换模型/换 key 不需重新部署；api_key 用 Fernet 加密存库（主密钥在 env）；embedding 有运行时维度守卫（非 1536 维报明确错误），换维度需全量重索引（UI 有提示） |
| Python 依赖管理 | **uv + 单一根 pyproject**（hatchling 多包映射：apps/api、apps/worker、packages/* 以顶层包 `api`/`worker`/`domain`/`llm`/`integrations`/`observability` 导入，目录布局不变） | uv workspace 要求每包独立 pyproject + 嵌套同名目录，会破坏本文档所有路径引用；模块化单体无需按包发版，单根项目更简 |
| 前端 | **Next.js 15 App Router + TypeScript + Ant Design 5** | 上游文档已定 |

---

## 2. 进程模型与数据流

```text
Telegram ──POST──▶ api /webhooks/telegram/{secret}
                    │ 1. secret 校验
                    │ 2. update_id 幂等落库（ON CONFLICT DO NOTHING → 直接 200）
                    │ 3. 入 arq 队列 process_update(update_id)
                    │ 4. 立即返回 200
                    ▼
                  redis (arq)
                    │
                    ▼
                  worker: process_update
                    │ 获取会话级 Redis 锁（同会话串行，防止回复交错）
                    │ 执行编排管线（见 §6）
                    │ 经 Bot API 发送回复 / 通知运营者
                    │ lead 变更 → 入队 sync_lead(lead_id)
                    ▼
                  worker: sync_lead ──▶ Google Sheets（幂等 upsert，失败退避重试）

浏览器 ──▶ Traefik（服务器既有实例）──▶ /api/* → api（后台 REST + cookie JWT）
                    └─▶ /*     → web（Next.js）
```

- api 与 worker 共享 `packages/` 下的全部业务代码，只是入口不同（FastAPI app vs arq WorkerSettings）。
- 所有 LLM 调用只发生在 worker 进程（含文档索引的 embedding）。

---

## 3. 仓库目录结构

```text
Mercury/
├── .github/
│   └── workflows/
│       ├── ci.yml              # lint + 测试（PR / push，见 §17）
│       └── deploy.yml          # 镜像 → GHCR → SSH 部署（main / 手动，见 §17）
├── apps/
│   ├── api/                    # FastAPI 入口
│   │   ├── main.py             # app 工厂、路由挂载、生命周期
│   │   ├── deps.py             # DI：会话、管理员认证（cookie JWT）、CSRF
│   │   ├── netguard.py         # SSRF 防护（URL 导入 / 供应商 base_url，§14）
│   │   └── routers/
│   │       ├── webhook.py      # Telegram webhook
│   │       ├── auth.py
│   │       ├── conversations.py
│   │       ├── leads.py
│   │       ├── knowledge.py
│   │       ├── metrics.py
│   │       ├── settings.py     # 模型供应商配置 API（§10）
│   │       ├── users.py        # 用户数据删除（§14）
│   │       └── health.py
│   ├── worker/
│   │   ├── main.py             # arq WorkerSettings
│   │   └── tasks/
│   │       ├── process_update.py
│   │       ├── extract_lead.py     # 回复送达后独立执行的线索提取
│   │       ├── index_document.py
│   │       ├── sync_lead.py
│   │       └── sweeper.py          # 兜底扫描器（arq cron，见 §6）
│   └── web/                    # 管理后台：Next.js 15 + AntD 5（独立 package.json）
│       ├── src/
│       │   ├── app/
│       │   │   ├── login/page.tsx
│       │   │   ├── (admin)/            # 登录态布局（侧边导航）
│       │   │   │   ├── layout.tsx
│       │   │   │   ├── dashboard/page.tsx        # 指标卡片
│       │   │   │   ├── conversations/page.tsx    # 会话列表+筛选
│       │   │   │   ├── conversations/[id]/page.tsx  # 消息流+来源+lead面板+接管
│       │   │   │   ├── leads/page.tsx
│       │   │   │   ├── leads/[id]/page.tsx
│       │   │   │   ├── knowledge/page.tsx        # 上传/启停/重建索引
│       │   │   │   └── settings/page.tsx         # 模型供应商配置
│       │   │   └── layout.tsx
│       │   ├── lib/api.ts      # fetch 封装（同域 /api，401 跳登录）
│       │   └── components/     # LeadPanel、SourceViewer、HandoffButton 等
│       └── middleware.ts       # 未登录重定向 /login
├── packages/
│   ├── domain/                 # 业务核心，不依赖 FastAPI/arq
│   │   ├── config.py           # 应用配置（§13 环境变量，pydantic-settings）
│   │   ├── texts.py            # 机器人固定文案（非 LLM 提示词）
│   │   ├── models.py           # SQLAlchemy ORM 模型（§4 的表）
│   │   ├── schemas.py          # Pydantic：LeadExtraction、TriageResult 等
│   │   ├── orchestrator.py     # §6 编排管线
│   │   ├── scoring.py          # §8 评分纯函数
│   │   ├── lead_merge.py       # §7 字段合并
│   │   ├── handoff.py          # §9 状态机
│   │   └── repositories.py     # 数据访问封装
│   ├── llm/
│   │   ├── client.py           # OpenAI 兼容客户端封装（base_url/model/费用记录）
│   │   ├── prompts.py          # 全部系统提示词常量
│   │   ├── rag.py              # 检索 + 受约束生成
│   │   ├── brain.py            # Brain 协议实现：triage+answer 聚合，注入编排层
│   │   ├── indexing.py         # 索引流程：解析→切分→embedding→版本化原子切换
│   │   ├── extraction.py       # 字段提取调用
│   │   ├── triage.py           # 意图/风险/是否需RAG 联合分类调用
│   │   ├── provider_config.py  # DbConfigSource：Fernet 加密、60s缓存+广播失效、DynamicChatClient
│   │   └── chunking.py         # 文档解析与切分
│   ├── integrations/
│   │   ├── telegram.py         # Bot API 封装（发消息、通知；无 token 时 LoggingSender 替身）
│   │   ├── locks.py            # Redis 会话锁（TTL+token+续期+Lua 释放，§6 第 1 步）
│   │   ├── netguard.py         # SSRF：URL 校验 + 安全抓取（逐跳重定向校验，§14）
│   │   ├── sheets.py           # Google Sheets LeadSyncPort 实现
│   │   └── ports.py            # LeadSyncPort 协议定义
│   └── observability/
│       ├── logging.py          # structlog 配置、trace_id、脱敏 processor
│       └── metrics.py          # 模型耗时/Token/成本记录
├── migrations/                 # Alembic（env.py 异步模板 + versions/）
├── alembic.ini
├── tests/
│   ├── unit/                   # scoring、merge、handoff、chunking
│   ├── integration/            # webhook→回复 全链路（LLM 打桩）
│   └── conftest.py             # testcontainers postgres、FakeLLM fixture
├── scripts/
│   ├── eval_rag.py             # 评测集跑分：命中率/拒答率报告（--fake 离线冒烟）
│   ├── eval/                   # 评测资产：sample-product.md（虚拟产品）+ evalset.json
│   └── set_webhook.py          # 注册 Telegram webhook
├── deploy/
│   ├── compose.yaml            # 本地开发栈（postgres/redis）
│   ├── compose.prod.yaml       # 生产：接入既有 Traefik（外部网络+labels）+ migrate/backup（§16）
│   ├── Dockerfile.app          # api/worker 共用镜像
│   ├── Dockerfile.web          # Next.js standalone 镜像
│   └── deploy.sh               # 服务器端：拉起→健康检查→失败自动回滚（§17）
├── docs/
├── pyproject.toml              # 单一根项目：依赖 + hatch 多包映射（§1）
└── .env.example
```

原则：`domain` 不 import FastAPI/arq/aiogram；`llm` 与 `integrations` 被 `domain.orchestrator` 通过构造注入（便于测试打桩）。

---

## 4. 数据库设计

沿用 MVP 文档 §7 的实体与命名，落成 DDL 要点如下（Alembic 首个 migration 按此生成）：

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE telegram_updates (          -- 幂等表
  update_id     BIGINT PRIMARY KEY,
  payload       JSONB NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued',  -- queued|processing|replied|extracting|done|failed|skipped
  picked_at     TIMESTAMPTZ,                     -- worker 抢占时间（处理租约起点）
  error         TEXT,
  received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at  TIMESTAMPTZ
);

CREATE TABLE users (
  id               BIGSERIAL PRIMARY KEY,
  telegram_user_id BIGINT NOT NULL UNIQUE,
  username         TEXT,
  first_name       TEXT,
  last_name        TEXT,
  language_code    TEXT,
  consent_status   TEXT NOT NULL DEFAULT 'notified',  -- notified|accepted|deleted
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
  id                   BIGSERIAL PRIMARY KEY,
  telegram_chat_id     BIGINT NOT NULL,
  user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status               TEXT NOT NULL DEFAULT 'ai_active',
    -- ai_active|handoff_pending|human_active|closed（迁移中加 CHECK）
  assigned_operator_id BIGINT,       -- MVP 单管理员恒为 1（内部 ID）；P1 建 operators 表
  started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_message_at      TIMESTAMPTZ,
  closed_at            TIMESTAMPTZ
);
CREATE UNIQUE INDEX one_open_conversation ON conversations (telegram_chat_id, user_id)
  WHERE status != 'closed';
  -- 只约束"未关闭会话唯一"——/reset 关旧建新不会违反唯一键

CREATE TABLE messages (
  id                  BIGSERIAL PRIMARY KEY,
  conversation_id     BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  telegram_message_id BIGINT,
  source_update_id    BIGINT REFERENCES telegram_updates(update_id) ON DELETE SET NULL,
    -- 产生该消息的 update（人工/系统消息为 NULL）
  delivery_key        TEXT,
    -- outbound 投递幂等键：reply:{update_id}|followup:{update_id}|ack:{update_id}|fallback:{update_id}
  direction           TEXT NOT NULL,       -- inbound|outbound
  sender_type         TEXT NOT NULL,       -- user|ai|operator|system
  content             TEXT NOT NULL,
  content_type        TEXT NOT NULL DEFAULT 'text',
  delivery_status     TEXT,                -- 仅 outbound：sending|sent|failed|uncertain
  answer_status       TEXT,                -- answered|refused|handoff（仅 AI outbound）
  source_chunk_ids    BIGINT[],            -- RAG 引用来源
  model_name          TEXT,
  prompt_tokens       INT,
  completion_tokens   INT,
  latency_ms          INT,
  confidence          REAL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON messages (conversation_id, created_at);
CREATE UNIQUE INDEX uniq_inbound_message ON messages (conversation_id, telegram_message_id)
  WHERE direction = 'inbound';
  -- 任务重试用 ON CONFLICT DO NOTHING，不产生重复 inbound
CREATE UNIQUE INDEX uniq_outbound_delivery ON messages (delivery_key)
  WHERE delivery_key IS NOT NULL;
  -- 每个投递意图至多一条 outbound；重试按 delivery_key 查 sent/sending 决定跳过或标 uncertain

CREATE TABLE knowledge_documents (
  id           BIGSERIAL PRIMARY KEY,
  title        TEXT NOT NULL,
  source_type  TEXT NOT NULL,              -- markdown|txt|pdf|url
  source_url   TEXT,
  storage_path TEXT,
  checksum     TEXT,
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending|indexing|active|disabled|failed
  version      INT NOT NULL DEFAULT 1,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE knowledge_chunks (
  id          BIGSERIAL PRIMARY KEY,
  document_id BIGINT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
  version     INT NOT NULL DEFAULT 1,      -- 对应 documents.version，重索引原子切换用
  chunk_index INT NOT NULL,
  content     TEXT NOT NULL,
  metadata    JSONB NOT NULL DEFAULT '{}',
  embedding   vector(1536) NOT NULL,
  UNIQUE (document_id, version, chunk_index)   -- 重试/并发重索引不产生重复 chunk
);
CREATE INDEX ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE leads (
  id                BIGSERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  conversation_id   BIGINT NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
  name              TEXT,
  company           TEXT,
  country           TEXT,
  business_email    TEXT,
  requirement       TEXT,
  team_size         TEXT,
  budget_range      TEXT,
  purchase_timeline TEXT,
  integrations      JSONB NOT NULL DEFAULT '[]',
  notes             TEXT,
  declined_fields   TEXT[] NOT NULL DEFAULT '{}',  -- 用户拒绝提供的字段，不再追问
  asked_demo        BOOLEAN NOT NULL DEFAULT false,  -- 提取的事实布尔：要过 Demo/报价（评分 +25）
  freebie_only      BOOLEAN NOT NULL DEFAULT false,  -- 仅求免费资源（评分 -20）
  score             INT NOT NULL DEFAULT 0,
  grade             TEXT NOT NULL DEFAULT 'low',   -- low|medium|high
  score_reasons     JSONB NOT NULL DEFAULT '[]',
  status            TEXT NOT NULL DEFAULT 'open',  -- open|synced|won|lost
  version           INT NOT NULL DEFAULT 1,        -- 实质变更 +1，是同步幂等键的组成部分
  external_crm_id   TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE handoffs (
  id              BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  reason          TEXT NOT NULL,   -- user_request|low_confidence|sensitive|high_intent|manual
  requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at     TIMESTAMPTZ,
  resolved_at     TIMESTAMPTZ,
  operator_id     BIGINT           -- MVP 恒为 1（内部管理员 ID，非 Telegram ID）
);
CREATE UNIQUE INDEX one_unresolved_handoff ON handoffs (conversation_id)
  WHERE resolved_at IS NULL;
  -- 每会话至多一个未解决的接管请求；通知型记录创建即 resolved（见 §9）

CREATE TABLE integration_jobs (
  id               BIGSERIAL PRIMARY KEY,
  integration_type TEXT NOT NULL,          -- google_sheets|twenty|hubspot
  entity_type      TEXT NOT NULL,          -- lead
  entity_id        BIGINT NOT NULL,
  idempotency_key  TEXT NOT NULL UNIQUE,   -- 如 "sheets:lead:42"
  payload          JSONB NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending', -- pending|running|done|failed
  attempts         INT NOT NULL DEFAULT 0,
  last_error       TEXT,
  next_retry_at    TIMESTAMPTZ,
  picked_at        TIMESTAMPTZ,             -- 处理租约起点，扫描器恢复卡死任务
  completed_at     TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE llm_providers (           -- 后台可配的模型供应商
  id             BIGSERIAL PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,     -- 展示名，如 "DeepSeek 官方"
  base_url       TEXT NOT NULL,
  api_key_enc    TEXT NOT NULL,            -- Fernet 密文，绝不存明文
  chat_model     TEXT NOT NULL,
  fallback_model TEXT,
  supports_json_schema BOOLEAN NOT NULL DEFAULT true,  -- 端点不支持严格 schema 时降级
  is_active      BOOLEAN NOT NULL DEFAULT false,
  last_test_at   TIMESTAMPTZ,
  last_test_ok   BOOLEAN,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_active_provider ON llm_providers ((true)) WHERE is_active;
  -- 全局至多一个激活供应商

CREATE TABLE audit_logs (
  id          BIGSERIAL PRIMARY KEY,
  actor_type  TEXT NOT NULL,   -- admin|system|ai
  actor_id    TEXT,
  action      TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id   BIGINT,
  metadata    JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

说明：

- 幂等的最终防线是 `telegram_updates.update_id` 主键，Redis 不作为幂等依据。
- `messages.answer_status = 'refused'` 聚合即得"知识库缺口"，不另建表。
- MVP 一个会话对应至多一条 lead（`conversation_id UNIQUE`），简化合并逻辑。

---

## 5. Webhook 接入（api 侧）

`POST /webhooks/telegram/{bot_secret}`：

1. 双重校验：URL 路径 `bot_secret` 与请求头 `X-Telegram-Bot-Api-Secret-Token`（setWebhook 时设置的 secret_token）均用 `secrets.compare_digest` 比较，任一不符返回 404。
2. 解析 body 取 `update_id`；`INSERT INTO telegram_updates ... ON CONFLICT DO NOTHING`，冲突（重复推送）直接返回 `{"ok": true}`。
3. `arq.enqueue_job("process_update", update_id)`，返回 200。总耗时目标 < 50ms。
4. 失败语义（三轮评审修订）：**数据库未提交 → 返回 503**，让 Telegram 重推（消息不在我们手里，绝不能吞）；畸形 payload → 200 直接吞（重推无益）。
5. **已落库、入队失败 → 返回 200**，由 worker 兜底扫描器闭环（见 §6）：update 只要进了表就一定会被处理，不依赖单次 enqueue 成功。

非文本消息（图片/语音等）：标记 `status='skipped'`，回复固定文案"目前仅支持文字消息"。

---

## 6. 编排管线（worker: process_update）

worker 端为确定性的显式管线，每一步可单测：

```text
process_update(update_id):
  0. 原子抢占：UPDATE telegram_updates SET status='processing', picked_at=now()
     WHERE update_id=$1 AND status IN ('queued','failed')
     —— 0 行命中说明已被处理或正在处理，直接结束（重复入队无害）
  0b. 顺序守卫：同 chat 存在更早的未完成 update（queued/processing，如扫描器恢复的
     旧消息）→ 回置 queued 让位重试，保证会话内按 update_id 序处理（三轮评审）
  1. 取 Redis 会话锁 conv:{chat_id}：TTL 60s、带随机 token、Lua 比对后释放、
     任务内每 20s 续期；拿不到 → 状态回置 'queued'，defer 2s 重新入队
  2. 加载/创建 user、conversation；保存 inbound message
     （唯一索引 + ON CONFLICT DO NOTHING，重试幂等）；更新 last_message_at
  3. 路由（只决策、不发送——所有分支统一产出 ReplyPlan）：
     a. 命令分支（不经 LLM）：
        /start → 欢迎语 + 简短隐私提示（更新 consent_status）
        /human → 幂等接管：已处于 pending/active 只回"人工已收到通知"；
                 否则 transition(handoff_pending) + 建 handoff + 回"已通知人工"
        /reset → 关旧会话建新会话（部分唯一索引允许），回确认语
     b. 静默态：status ∈ {human_active, handoff_pending}
        → 通知运营者"用户有新消息"，ReplyPlan 为空
     c. triage（structured output，输入近 6 轮对话；预算见下，失败按
        needs_rag=true / risk=none 继续）：
        TriageResult { risk: none|privacy|contract|security|payment|complaint,
                       purchase_intent: bool, needs_rag: bool, language: str }
        risk != none → ReplyPlan = "已为您转接人工"模板 +
        transition(handoff_pending, sensitive)，不再走 RAG
     d. needs_rag → RAG（预算 = 总 deadline 剩余时间）；检索不足/生成失败/预算耗尽
        → 拒答模板 + 写 handoffs(low_confidence) 通知（状态不变），answer_status='refused'
     e. 闲聊/寒暄 → 轻量模板式回复，不检索
  4. 统一投递（所有分支唯一的发送出口，两阶段）：对 ReplyPlan 中每条消息，
     以 delivery_key（reply:{update_id} / ack:{update_id}）落
     outbound(delivery_status='sending') → sendMessage → 更新 'sent' 并回填
     telegram_message_id。重试时按 delivery_key 查询：已 'sent' → 跳过；
     残留 'sending' → 标 'uncertain' 不重发（宁可漏发可人工补），通知运营者
  5. 标记 update：需要提取线索（triage.purchase_intent 或已有 lead）
     → status='replied' 并 enqueue extract_lead(update_id)；
     否则 status='done', processed_at=now()
  6. 异常处理：仅第 0–4 步的异常 → status='failed' + error + 安全兜底文案
     （delivery_key fallback:{update_id}，经统一投递）+ 通知运营者；
     第 5 步之后不再有任何用户可见动作

extract_lead(update_id)  —— 独立任务，回复已送达后执行，失败绝不打扰用户：
  0. 原子抢占：replied → extracting（并发重复入队只有一个通过；拿不到会话锁回置 replied）
  1. 取同一会话锁；字段提取（§7，超时 30s、重试 1 次、可切 fallback）
     → 合并 → 评分（§8）
  2. 缺失关键字段且不在 declined_fields → follow_up_question 以
     delivery_key followup:{update_id} 经统一投递单独发送
  3. grade 升为 high → 写 handoffs(high_intent) + 通知（会话状态不变）
  4. 实质变更 → leads.version+1，写 integration_jobs + enqueue sync_lead
  5. 成功或最终失败均置 update status='done', processed_at=now()
     （失败记 error + 通知运营者）；绝不重跑 triage/RAG，绝不发送"系统繁忙"
```

LLM 调用失败策略：**用户回复路径（triage/RAG）不做长重试**——triage 失败按默认值继续，RAG 失败走拒答转人工；只有提取/摘要等非用户路径允许重试与 fallback 模型。任何失败都不能让消息丢失或无响应。

**兜底扫描器（arq cron，每 60s）**：统一模式是**先原子重置、再入队**——只入队 `RETURNING` 出来的 ID，与第 0 步的抢占条件闭环：

1. `processing` 租约过期：`UPDATE telegram_updates SET status='queued', picked_at=NULL WHERE status='processing' AND picked_at < now() - interval '5 min' RETURNING update_id` → enqueue `process_update`；
2. `queued` 超 60s 未被消费（覆盖"DB 已提交但入队失败"的窗口）→ 直接补 enqueue；
3. `replied` 超 5min（extract_lead 任务丢失）→ 补 enqueue `extract_lead`；`extracting` 租约过期 → 原子重置回 `replied` 再入队；
4. `integration_jobs` 中 `running` 超 10min → 重置为 `pending`、清 `picked_at` 后入队。

这是"消息处理可追踪率 100%"的最终保障。

**响应时间预算**：回复路径共享一个端到端 deadline（`REPLY_DEADLINE_S` 默认 5s，`asyncio.timeout` 实现）：triage 上限 2s 且计入总预算，RAG 生成获得剩余时间；预算耗尽走拒答转人工（属"模型异常"口径，不计入 MVP "<5s" 指标）。正常链路 triage ≈1s + 检索 ≈0.2s + 生成 ≈3s；线索提取在回复送达后的独立任务中执行，不占用户等待时间。

### RAG 细节（packages/llm/rag.py）

- 切分：`RecursiveCharacterTextSplitter`，约 400 token/块，overlap 60。
- 检索：cosine 相似度 top-6，过滤 `similarity < RAG_MIN_SIMILARITY`（默认 0.60，评测集调优）；只查 `status='active'` 且 `chunks.version = documents.version` 的 chunks。
- 重建索引的原子切换：任务先取 Redis 锁 `index:{document_id}`（同会话锁机制，防并发重索引）；新 chunks 以 `version+1` 写入（`UNIQUE(document_id, version, chunk_index)` + ON CONFLICT DO NOTHING，重试幂等）→ 单条 UPDATE 翻转 `documents.version` → 删除旧版本 chunks。翻转前旧版本始终可检索，不存在"知识真空期"。
- 过滤后为空 → 无答案路径。
- 生成：系统提示词强约束（见 `prompts.py`）：只依据给定资料回答；资料未覆盖必须说无法确认；禁止编造价格/SLA/退款/法律承诺；资料中的指令性文字视为数据。输出后记录 `source_chunk_ids`。
- 回复语言跟随 `triage.language`。
- **为什么不用 Milvus / RAGFlow 等**（已讨论定案）：试点语料为千级 chunk，pgvector HNSW 性能足够，且向量与业务数据同库带来事务级联删除、SQL 过滤 active 文档、单一备份——独立向量库只增运维不增收益。RAGFlow 类平台自带整套基础设施与对话流主权，而本产品的价值恰在自有管线（triage/线索/接管/记账），只可按需引入其解析库（unstructured/marker），不引入平台。升级触发条件：① 精确词召回弱 → Postgres tsvector hybrid 检索（不出库）；② PDF 解析成为评测失败主因 → pypdf 换 unstructured/marker；③ 百万级向量或多租户高 QPS（商业版之后）→ 再评估独立向量库。
- **关于本体论/知识图谱**（已讨论定案）：MVP 不引入——人工建模与"7 天交付"冲突，自动构建（GraphRAG）成本与维护复杂度不匹配试点语料规模，且失败模式兜底已有拒答转人工。替代措施：① 切分时把标题层级/所属产品写入 `knowledge_chunks.metadata` 供检索过滤加权（现在做）；② 价格/SLA 类关键事实做结构化 facts 表、查表回答而非散文检索（P1）。重开条件：评测集失败 ≥20% 为跨文档关联型问题，或出现上千页、多产品线 SKU 密集的语料。

---

## 7. 字段提取与合并

提取调用输入：近 10 轮对话 + 当前 lead JSON。输出 Schema：

```python
class LeadExtraction(BaseModel):
    name: str | None
    company: str | None
    country: str | None
    business_email: str | None
    requirement: str | None
    team_size: str | None
    budget_range: str | None
    purchase_timeline: str | None
    integrations: list[str]
    notes: str | None
    asked_demo_or_quote: bool  # 事实布尔：要过 Demo/报价（供 §8 评分，持久化到 leads.asked_demo）
    freebie_only: bool  # 事实布尔：仅求免费资源（持久化到 leads.freebie_only）
    refused_fields: list[str]  # 本轮用户明确拒绝提供的字段
    follow_up_question: str | None  # 建议追问（至多一个，可为 None）
```

合并规则（`lead_merge.py`，纯函数）：

- 新值非空且与旧值不同 → 覆盖，并把 `{field, old, new}` 写入 audit_logs。
- 新值为空 → 保留旧值（绝不用空值抹掉已有信息）。
- `refused_fields` 并入 `declined_fields`；此后提取提示词中告知模型这些字段不再追问。
- `business_email` 做格式校验，无效则丢弃。

---

## 8. 评分引擎（scoring.py，纯函数、表驱动）

```python
RULES = [
    ("company_email",   +15, lambda l: 有 business_email 且非免费邮箱域),
    ("clear_need",      +20, lambda l: requirement 非空),
    ("team_size_fit",   +15, lambda l: team_size 达标),
    ("budget_given",    +15, lambda l: budget_range 非空),
    ("timeline_30d",    +20, lambda l: purchase_timeline 解析为 30 天内),
    ("asked_demo",      +25, lambda l: leads.asked_demo 事实列为真——由 extraction 显式输出，
                              # 而非 notes 魔法标记（M5 修订）),
    ("freebie_only",    -20, lambda l: leads.freebie_only 事实列为真),
]
# 0–29 low | 30–59 medium | ≥60 high
```

- 免费邮箱域名单（gmail/outlook/yahoo/qq/163 等）为常量，可配置。
- 每次评分输出命中的规则名列表存入 `score_reasons`，后台原样展示。
- 阈值与分值集中在一个 dict，未来按客户配置化。

---

## 9. 人工接管状态机（handoff.py）

```text
ai_active ──user_request/sensitive/manual──▶ handoff_pending ──管理员接管──▶ human_active
    ▲                                             │                             │
    └─────────────────管理员恢复 AI────────────────┴─────────────────────────────┘
任意状态 ──管理员关闭──▶ closed
（low_confidence / high_intent 为通知型触发：写 handoffs + 提醒运营者，不改会话状态）
```

- **静默型触发**（`user_request` / `sensitive` / `manual`）→ 进入 `handoff_pending`：AI 只发一次"已通知人工"确认，此后新消息仅转通知、不再回答——满足 MVP §10.1"用户要求人工后 AI 立即停止自动回复"。
- **通知型触发**（`low_confidence` / `high_intent`）→ 只写 `handoffs` 记录并提醒运营者，会话保持 `ai_active`：低置信度已用拒答模板回应过，高意向用户正在顺畅对话中，强行静默反而伤转化。通知型记录**创建即 `resolved_at=now()`**（纯提醒，无处理闭环），不占用 `one_unresolved_handoff` 唯一索引。
- `/human` 幂等：会话已处于 `handoff_pending` / `human_active` 时仅回复"人工已收到通知"，不重复 transition、不新建 handoff（`one_unresolved_handoff` 部分唯一索引兜底防并发）。
- `human_active` 与 `handoff_pending` 下 worker 管线在第 4 步短路——这是验收要求 100% 正确的路径，必须有集成测试覆盖。
- 状态变更全部经 `handoff.py` 中的 `transition(conv, event)` 单一入口，非法迁移抛异常；变更写 audit_logs；管理员接管时回填 `accepted_at`（接管确认与"是否停 AI"解耦——停 AI 由状态决定）。
- MVP 单管理员：`assigned_operator_id` / `operator_id` 恒为 1（内部管理员 ID，非 Telegram ID）；P1 多运营者时再建 operators 表。
- 管理员在后台发消息（`POST /api/conversations/{id}/messages`）→ api 直接调 Telegram 发送，`sender_type='operator'`。

---

## 10. 管理后台

### API（api 侧，全部需 cookie JWT）

沿用 MVP 文档 §8 的路径，补充契约要点：

- `POST /api/auth/login` `{username, password}` → set-cookie；`POST /api/auth/logout`。
- `GET /api/conversations?status=&q=&page=` → 分页列表（最后消息摘要、lead grade）。
- `GET /api/conversations/{id}` → 消息流（含 `source_chunk_ids` 展开的来源片段）、lead 面板、handoff 历史。
- `POST /api/conversations/{id}/handoff` / `resume-ai` → 状态机 transition。
- `PATCH /api/leads/{id}` → 人工修正字段后自动重算评分。
- `POST /api/leads/{id}/sync` → 手动重试同步。
- `POST /api/knowledge/documents`（multipart 上传或 `{url}`）→ 建记录 + enqueue `index_document`。
- `GET /api/metrics/overview` → 消息数/会话数/自动回复数/接管数/线索数（按日聚合）。
- `GET /api/metrics/costs` → 按日 token 与估算成本。
- `GET /api/metrics/knowledge-gaps` → `answer_status='refused'` 的问题聚合列表。
- 模型供应商配置：
  - `GET /api/settings/llm-providers` → 列表（api_key 一律脱敏为末 4 位，写入后不可读回明文）；
  - `POST /api/settings/llm-providers` / `PATCH /{id}`（请求含新 key 才更新密文，否则保留）；
  - `POST /api/settings/llm-providers/{id}/activate` → 激活并 Redis 广播配置失效；
  - `POST /api/settings/llm-providers/{id}/test` → 最小对话调用，返回延迟/成败并回填 last_test_*；
  - `DELETE /api/settings/llm-providers/{id}`（激活中的不可删）。
  - 所有变更写 audit_logs（metadata 不含明文 key）。

### 页面（apps/web）

`/login`、`/conversations`（列表+筛选）、`/conversations/[id]`（消息流 + 来源侧栏 + lead 面板 + 接管/恢复按钮 + 人工发消息框）、`/leads`、`/knowledge`（上传/启停/重建索引）、`/settings`（模型供应商：增删改、激活、脱敏展示、连接测试按钮）、`/dashboard`（指标卡片）。会话详情页 5 秒轮询刷新（MVP 不做 WebSocket）。

---

## 11. Google Sheets 同步（sync_lead）

- `ports.py` 定义 `LeadSyncPort.upsert_lead(lead) -> external_id`，`sheets.py` 实现。
- Sheet 结构：第一行表头（Lead ID、Telegram、Name、Company、…、Score、Grade、Summary、Last Contact、Synced At），按 `Lead ID` 列查找行 → 有则整行更新，无则 append。
- **幂等键带版本**：`sheets:lead:{id}:v{version}`（`leads.version` 实质变更时 +1）——每次变更都能建新任务，不被首个 job 的唯一键挡住。任务执行时从 DB 读取 lead **当前**状态写入（payload 仅作审计快照），即使乱序执行也只会写入最新数据。
- 任务流程：置 `status='running', picked_at=now()` → 调用 → 成功 `done` + `completed_at`，回填 `leads.external_crm_id`；失败 attempts+1，`next_retry_at = now + 2^attempts 分钟`（arq defer），attempts ≥ 5 → `failed`，通知运营者，后台可手动重试；`running` 超 10min 由 §6 兜底扫描器恢复。
- 摘要（Summary 列）：同步时用 LLM 生成 2–3 句对话摘要（失败则留空，不阻塞同步）。

---

## 12. LLM 抽象层（packages/llm/client.py）

- 基于 `openai` SDK。配置经 `ProviderConfigSource` 协议解析，优先级：**DB 激活供应商（llm_providers.is_active）→ env 兜底**（`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_CHAT_MODEL`/`LLM_CHAT_MODEL_FALLBACK`）。M1–M7 只有 `EnvConfigSource`；M8 加 `DbConfigSource`：进程内缓存 60s + 激活/修改时 Redis pub/sub 广播失效，worker 无需重启即热切换。
- api_key 存库用 Fernet 加密（`cryptography`），主密钥 `SETTINGS_ENCRYPTION_KEY` 仅在 env；任何 API 响应与日志只出现末 4 位。
- embedding 也可后台配（`llm_providers.embed_model`，`DynamicEmbedder` 解析：供应商配置 → env 兜底）；运行时维度守卫拒绝非 1536 维向量（换维度需全量重索引，UI 有提示）——M8 后修订，替代原"仅 env"限制。
- 统一封装 `chat(messages, schema=None, purpose="rag|triage|extract|summary")`，按 purpose 分两档策略：
  - **用户回复路径**（triage/rag）：共享端到端 deadline（`REPLY_DEADLINE_S`，默认 5s）——triage 上限 2s 且计入总预算，RAG 生成获得剩余时间；不做同调用重试、不切 fallback，超时或失败立即降级（triage 按默认值继续、RAG 走拒答转人工）；
  - **非用户路径**（extract / summary / 索引，超时 30s）：重试 1 次，连续失败切 fallback 模型；
  - 每次调用记录 purpose、model、tokens、latency、估算成本（端点缺 usage 字段时记 NULL，不臆造）；
  - `schema` 非空且供应商 `supports_json_schema` → 严格 structured outputs；否则降级为 json_object 模式 + 提示词约束。两条路径都过 Pydantic 校验，失败修复重试一次后抛 `LLMOutputError`。
- 测试用 `FakeLLM` 实现同一接口，按 purpose 返回预置结果。
- **为什么不用 LiteLLM**（已讨论定案）：目标供应商（OpenAI/DeepSeek/Kimi/Qwen/GLM/Groq/OpenRouter/vLLM）全部提供 OpenAI 兼容端点，base_url 抽象已覆盖换供应商需求；purpose 打标、入库记账、Pydantic 校验这层业务封装无论如何都要写，LiteLLM 只是多垫一层大依赖。且不锁门——将来需要多供应商路由/配额时，部署 LiteLLM Proxy（对外即 OpenAI 兼容端点），改 `LLM_BASE_URL` 指过去即可，代码零改动。

---

## 13. 配置清单（.env.example）

```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=        # 随机 32+ 字符：URL 路径 + setWebhook secret_token 头双重校验
OPERATOR_TELEGRAM_CHAT_ID=      # 人工提醒接收者

# LLM（OpenAI 兼容；作为兜底配置——后台配置了激活供应商时以 DB 为准）
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
SETTINGS_ENCRYPTION_KEY=        # Fernet 主密钥，加密后台录入的供应商 api_key
LLM_CHAT_MODEL=
LLM_CHAT_MODEL_FALLBACK=
LLM_EMBED_MODEL=text-embedding-3-small
ALLOW_PRIVATE_LLM_BASE_URL=false  # 后台配置的 base_url 默认禁内网/云元数据地址；自建 vLLM 时显式打开
RAG_MIN_SIMILARITY=0.60
RAG_TOP_K=6
REPLY_DEADLINE_S=5              # 用户回复路径端到端预算（triage+检索+生成）

# 数据
DATABASE_URL=postgresql+asyncpg://mercury:***@postgres:5432/mercury
REDIS_URL=redis://redis:6379/0

# 后台
ADMIN_USERNAME=
ADMIN_PASSWORD_HASH=            # bcrypt
JWT_SECRET=
PUBLIC_BASE_URL=                # 演示环境 https 域名

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON=    # 路径或 base64
LEADS_SPREADSHEET_ID=

# 运行
LOG_LEVEL=INFO
DATA_RETENTION_DAYS=180

# 部署（既有 Traefik 接入）
TRAEFIK_NETWORK=proxy           # 服务器上既有 Traefik 所在的 docker 网络名
PUBLIC_HOST=                    # 对外域名（PUBLIC_BASE_URL 的 host 部分），用于路由规则
```

---

## 14. 可观测性与安全

- structlog JSON 日志；api 中间件生成 `trace_id` 并随 arq job 透传，一条消息全链路同一 trace_id（满足"可追踪率 100%"）。
- 脱敏 processor：email 打码（`t***@example.com`）、任何形如 token/key 的值替换为 `[redacted]`；`TELEGRAM_BOT_TOKEN` 出现在 URL 中的场景（Bot API 调用日志）必须过滤。
- `GET /health/live`（进程存活）与 `/health/ready`（DB + Redis ping）。
- 提示词注入防线在代码层落实：用户消息与知识库 chunk 一律放在 user role 内容里，系统规则只在 system prompt；不给模型任何工具/函数可调用（结构化输出不算工具），所有写操作由管线代码完成。
- 后台 Cookie：`HttpOnly` + `Secure` + `SameSite=Lax`；写接口要求自定义头（`X-Requested-With: fetch`）作 CSRF 防线——跨站表单无法携带自定义头。
- 登录限流：每 IP 5 次/分钟（Redis 计数），失败与锁定写 audit_logs。
- URL 导入 SSRF 防护（`integrations/netguard.py`，api 与 worker 共用）：仅 http/https；DNS 解析后拒绝私网/链路本地/云元数据地址；worker 实际抓取关闭自动重定向、**逐跳重新校验**、响应上限 10MB、超时 20s（解析后 IP 固定为 P1）。上传限制：≤20MB、PDF ≤200 页。
- 后台配置的 LLM base_url 默认同样拒绝内网地址（`ALLOW_PRIVATE_LLM_BASE_URL=true` 显式放开，用于自建推理服务场景）。
- 生产安全底线（三轮评审）：`PUBLIC_BASE_URL` 为 https 时启动强制校验——JWT_SECRET ≥32 字符、管理员凭据/加密主密钥/webhook secret 齐备，否则拒绝启动；JWT 校验含 `sub == admin_username`。
- 用户数据删除：`DELETE /api/users/by-telegram/{telegram_user_id}`——内容表靠 DDL 级联（users→conversations→messages/handoffs、users→leads）；integration_jobs（无外键）与 audit_logs 中该用户相关 entity 的记录（其 metadata 含 lead 字段新旧值）由删除流程显式清理；删除动作本身另记一条匿名 audit。数据保留期由每日 arq cron 按 `DATA_RETENTION_DAYS` 清理。

---

## 15. 测试策略

- **单元**（无外部依赖）：scoring 全规则矩阵、lead_merge 覆盖/保留/拒绝路径、handoff 全部合法与非法迁移、chunking、邮箱域判断。
- **集成**（testcontainers 起 postgres+redis，LLM 用 FakeLLM）：
  - 同一 update_id 推两次 → 只有一条消息、一条 lead；
  - `human_active` 下 inbound → 无 AI 回复；
  - 检索无结果 → 拒答文案 + handoff(low_confidence) 记录；
  - 高意向对话 → 评分 ≥60 + 通知调用 + integration_job 创建；
  - Sheets 打桩抛错 → job 重试计划正确、lead 数据完好；
  - 任务中途失败后重试 → inbound 不重复、已发送回复不二次发送（`uncertain` 标记正确）；
  - `/reset` 后能创建新会话（部分唯一索引验证）；
  - 兜底扫描器恢复"已落库未入队"与"processing 租约过期"的 update；
  - lead 第二次变更能生成新的同步任务（版本化幂等键）；
  - 回复送达后 extraction 失败 → 用户收不到"系统繁忙"、不重跑 RAG，update 仍到 `done`；
  - 重复 `/human` → 只收到确认文案，不产生第二条未解决 handoff；
  - 扫描器把超时 `processing` 重置为 `queued` 后，能被再次原子抢占并处理完成；
  - 同一文档重试/并发重索引不产生重复 chunk（唯一约束 + 文档锁）。
- **评测**：`scripts/eval_rag.py` 对 30–50 问评测集输出正确率/拒答率报告，作为 RAG_MIN_SIMILARITY 调参依据（对应 MVP 指标 85%/95%）。
- MVP 文档 §10.1 的每一条必测用例都要能指到一个具体测试函数。

---

## 16. 部署（deploy/compose.yaml）

服务：`api`（uvicorn）、`worker`（arq）、`web`（next start）、`postgres`（`pgvector/pgvector:pg16` 镜像 + volume）、`redis`（appendonly + volume）。

**不部署 Traefik**——服务器上已有运行中的 Traefik 实例，本项目只接入：

- compose 声明外部网络：`networks: { proxy: { external: true, name: ${TRAEFIK_NETWORK} } }`；`api` 与 `web` 同时加入 `proxy` 和项目内部网络，`postgres`/`redis`/`worker` 只在内部网络。
- 路由靠 labels 声明：`traefik.enable=true`；``Host(`${PUBLIC_HOST}`) && PathPrefix(`/api`,`/webhooks`,`/health`)`` → api（优先级高），``Host(`${PUBLIC_HOST}`)`` → web；各自声明 `loadbalancer.server.port`。
- HTTPS/证书由既有 Traefik 负责；labels 中的 entrypoint 与 certresolver 名称**按服务器现有 Traefik 配置填**（常见为 `websecure` / `letsencrypt`，接入前先确认）。
- 本项目不向宿主机开放任何端口（没有 `ports:`），一切入口经既有 Traefik。
- api/worker 同一镜像（多阶段 Dockerfile，uv 安装），不同 command。
- migration 以一次性 `api alembic upgrade head` 服务在启动时执行。
- 备份：cron 容器每日 `pg_dump` 到 volume（试点阶段够用）。

---

## 17. CI/CD（GitHub Actions）

### 工具链定案

- Python：**ruff**（lint + format 检查）、**mypy**（基础严格度）、**pytest**；用 `astral-sh/setup-uv` action 带依赖缓存。
- Web：**pnpm** + ESLint + `tsc --noEmit` + `next build`。
- 镜像仓库：**GHCR**（`ghcr.io`，用内置 `GITHUB_TOKEN` 推送，不需要额外密钥）。

### ci.yml — 质量门禁（所有分支 push + PR）

两个并行 job：

- `python`：`uv sync` → `ruff check` + `ruff format --check` → `mypy` → `pytest`（单元 + 集成）。
  集成测试依赖用 GitHub Actions **services 容器**：`pgvector/pgvector:pg16` + `redis:7`；LLM 全部走 FakeLLM，**CI 不需要也不配置任何真实模型 key**。
- `web`：`pnpm install` → lint → `tsc --noEmit` → `next build`。

main 开分支保护：CI 全绿才能合并。单人开发也走「短命分支 + PR」，让 CI 卡住坏提交，同时 PR 历史就是变更日志。

### deploy.yml — 发布（push 到 main 自动触发 + workflow_dispatch 手动）

1. buildx 构建两个镜像——`mercury-app`（api/worker 共用，见 §16）与 `mercury-web`——tag 为 `sha-<short>` 和 `latest`，push GHCR（启用 gha 层缓存）。
2. SSH 到演示服务器（secrets：`DEPLOY_HOST` / `DEPLOY_USER` / `DEPLOY_SSH_KEY`），执行 `docker compose pull && docker compose up -d`。服务器上的 compose 引用 GHCR 镜像；migration 由 §16 的一次性 alembic 服务在启动时执行。
3. 部署后验证：`curl --fail --retry 12 --retry-delay 5 --retry-all-errors "$PUBLIC_BASE_URL/health/ready"`（`PUBLIC_BASE_URL` 本身已含 `https://`，不要重复拼协议）。服务器部署脚本在 pull 前记录当前运行的镜像 tag，健康检查失败即用该 tag 自动回滚，workflow 标红。
4. **回滚**：`workflow_dispatch` 接受输入 `image_tag`（默认 `latest`）——手动触发并填上一个可用的 `sha-*` tag 即回滚，不需要额外机制。

约定：服务器上的 `.env`（含所有真实密钥）只存在于服务器，绝不进仓库或 Actions secrets；Actions secrets 只放部署 SSH 三件套。

---

## 18. 实现顺序（代码生成里程碑）

每个里程碑独立可验证，验收不过不进入下一个。M1–M4 即 MVP 文档 §15 的"最小纵向闭环"。

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| **M1 脚手架** | uv 项目、目录骨架、settings、structlog、Alembic 首个 migration（§4 全部表）、compose（postgres/redis）、健康检查、ruff/mypy 配置、**ci.yml** | `docker compose up` 后 `/health/ready` 通过；migration 可升可降；首个 PR 上 CI 全绿 |
| **M2 消息闭环骨架** | webhook 幂等接收、arq 队列、user/conversation/message 落库、echo 回复、会话锁 | 真实 bot 收发消息；重复推送不产生重复记录 |
| **M3 知识库** | 文档解析/切分/embedding/入库、检索函数、`index_document` 任务、eval 脚本 | 评测脚本能对样例文档跑出检索命中报告 |
| **M4 受约束 RAG** | triage + RAG 生成 + 拒答路径接入管线，来源记录 | 演示剧本问题 1–2 正确回答且有来源；库外问题拒答 |
| **M5 线索** | extraction/merge/scoring/追问、declined_fields | 演示剧本问题 3–4 产生 high 线索且理由正确；拒绝后不再追问 |
| **M6 人工接管** | 状态机、/human、通知、命令处理 | `human_active` 下 AI 静默的集成测试通过 |
| **M7 Sheets 同步** | integration_jobs、sync_lead、重试退避、摘要 | 断网重试后数据无丢失；Sheet 中行幂等更新 |
| **M8 后台与部署** | 全部后台 API、Next.js 页面、认证、模型供应商配置（llm_providers + DbConfigSource + 加密 + 连接测试）、**deploy.yml（GHCR + SSH 部署 + 回滚）**、接入既有 Traefik（外部网络 + labels）、备份 | 完整跑通 MVP 文档 §10.2 演示验收剧本；后台切换供应商后 worker 不重启即生效；push main 自动发布且健康检查通过 |

---

## 19. 后续代码生成的约定

- 每个里程碑开工前先读本文档对应章节 + MVP 文档相关小节；接口、表名、状态值以本文档为准，不即兴改名。
- 新增设计决策（本文档未覆盖的）落回本文档，保持它是唯一实现级事实来源。
- Python 3.12 语法基线；全链路 async；`domain` 包保持零框架依赖。
- 提示词全部集中在 `packages/llm/prompts.py`，中英双语模板，禁止散落在业务代码里。

---

## 20. 商业路线与多客户架构（v1.4，2026-08-30 定案）

**路线：产品化定制服务**——先给客户定制交付，但按 SaaS 架构开发；拿到 3–5 个付费客户后再决定是否开放标准 SaaS。当前形态：**单一代码库 + 单一 main 分支 + 每客户独立 Docker 实例（独立数据库）**。

### 20.1 80% 标准内核（禁止按客户改代码）

消息管线与幂等机制（§5/§6）、RAG 与拒答路径、线索提取/合并/评分引擎、人工接管状态机（§9）、同步任务框架（§11）、后台管理端、部署管线。这些只能通过版本升级演进，所有客户实例跟随 main。

### 20.2 20% 配置面（每客户实例只改配置，不改代码）

| 定制点 | 载体 |
|---|---|
| 品牌名 / 回复语气 | env：`BRAND_NAME`、`BOT_TONE_HINT`（注入欢迎语与 RAG 系统提示词） |
| 评分规则（分值/阈值/团队规模下限/免费邮箱域） | env：`SCORING_OVERRIDES`（JSON，见 `domain/scoring.py::config_from_json`） |
| Bot Token / 运营者通知 | env：`TELEGRAM_BOT_TOKEN`、`OPERATOR_TELEGRAM_CHAT_ID` |
| LLM 供应商与模型 | 后台「模型配置」页（llm_providers 表，§12） |
| 知识库内容 | 后台「知识库」页上传 |
| CRM 目标 | `LeadSync` 端口的实现选择（现有 gspread；新 CRM = 新实现类，不动管线） |
| 数据保留期 / 调优参数 | env：`DATA_RETENTION_DAYS`、`RAG_*` 等 |

**红线：代码里不得出现任何客户名称、客户专属分支、客户专属 if。**

### 20.3 租户边界预留（migration 0005）

核心表（telegram_updates、users、conversations、leads、knowledge_documents、integration_jobs、llm_providers、audit_logs）均含 `tenant_id BIGINT NOT NULL DEFAULT 1`；唯一约束已按租户作用域：`(tenant_id, telegram_user_id)`、one_open_conversation 含 tenant_id、one_active_provider = 每租户一个激活供应商。**独立实例阶段 tenant_id 恒为 1，查询不做租户过滤**——这是刻意的：单租户实例加租户过滤只增加出错面。

### 20.4 SaaS 化转换清单（3–5 个付费客户后再做，现在不做）

1. `telegram_updates` PK 改 `(tenant_id, update_id)`（不同 bot 的 update_id 可能撞）；
2. 所有查询加租户过滤（repositories 层集中改），Redis 锁 / delivery_key / arq 任务参数加租户前缀；
3. tenants 表 + bot token 按租户入库（Fernet 加密，复用 §12 机制）+ webhook 路由按 token 区分租户；
4. 后台登录改多租户账号体系；备份/删除数据 API 按租户隔离；
5. 数据合并：各客户库导入时 tenant_id 重编号。

### 20.5 阶段闸门

- 现在 → 3 个付费客户：只做定制交付，验证付费意愿与交付成本；
- 3–5 个付费客户：若定制点收敛（配置面覆盖 ≥80% 需求）→ 启动 20.4；若发散 → 维持独立实例模式收服务费。
