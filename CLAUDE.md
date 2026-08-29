# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

用户偏好中文，请使用中文与用户交流。

## 仓库现状

这是一个全新仓库，**目前还没有任何代码**。两份核心文档：

- [docs/Telegram-AI-Lead-System-MVP.md](docs/Telegram-AI-Lead-System-MVP.md) — 产品需求与边界的事实来源（其 §6 技术建议已被技术方案替代）：用企业知识库通过 RAG 回答客户问题，从对话中提取并评分销售线索，必要时转人工，并将线索同步到 CRM / Google Sheets。
- [docs/technical-design.md](docs/technical-design.md) — **实现级技术方案（写代码以它为准）**：所有选型已定案（aiogram、arq、SQLAlchemy async、gspread、纯 Python 编排管线不用 LangGraph）、完整 DDL、编排管线、状态机、API 契约、环境变量清单，以及 M1–M8 实现里程碑顺序。

写任何代码前先读技术方案对应章节；表名、状态值、接口以技术方案为准，不即兴改名。新的设计决策要落回技术方案文档。

## 当前进度

M1 脚手架、M2 消息闭环骨架、M3 知识库（2026-08-29）、M4 受约束 RAG、M5 线索、M6 人工接管（2026-08-30）已完成。下一步：M7 Sheets 同步（技术方案 §18）。

M6 说明：状态机在 `domain/handoff.py`——纯函数迁移表 `next_status()` + 唯一变更入口 `transition()`（非法迁移抛 HandoffError，变更写 audit）；静默型触发（user_request/sensitive/manual）→ handoff_pending，通知型（low_confidence/high_intent）创建即 resolved 不改状态；/human 幂等；静默态下非文本消息也只转通知不回"仅支持文字"。管理端 accept/resume_ai/close 的 API 在 M8 挂接（直接调 transition）。坑：structlog 的 kwarg 不能叫 `event`（与事件名参数冲突）。

M5 说明：管线出现购买意图（或已有 lead）→ update 标 `replied` + 入队 `extract_lead` 独立任务（提取→合并→评分→追问→高意向通知→版本化同步任务行）；评分/合并是纯函数（`domain/scoring.py`/`lead_merge.py`），LLM 只输出事实（含 asked_demo_or_quote/freebie_only 两个事实布尔，migration 0002 加了对应列）；追问有代码层兜底——关键字段全被填/拒后即使 LLM 给了问题也不发。integration_jobs 行已创建但 sync_lead 的 enqueue 留给 M7（TODO 标注）。注意 ORM UPDATE 会同步内存对象，版本号必须先算后用（见 run_extract_lead 注释）。

M4 说明：LLM 依赖经 `Brain` 协议注入编排层（实现在 `llm/brain.py`，测试用 conftest 的 FakeBrain）；提示词全部在 `llm/prompts.py`（拒答用 NO_ANSWER_MARKER 哨兵）；端到端预算 `Deadline` 在 `domain/schemas.py`（triage 上限 2s 计入总预算，RAG 拿剩余）；chat 客户端双档策略——用户路径不重试不切 fallback，非用户路径重试1次+fallback。**真实模型验收**：配好 `.env`（LLM_API_KEY/LLM_CHAT_MODEL）后跑 `uv run python scripts/eval_rag.py --with-answers`，看"生成级报告"两个指标。

M2 说明：业务管线在 `domain/orchestrator.py`（MessageSender/ConversationLocker 协议注入，arq 任务只是薄包装）；echo 回复是 M4 RAG 的占位；/human 仅通知（状态机在 M6）；无 `TELEGRAM_BOT_TOKEN` 时自动用 LoggingSender 替身，本地无需真实 bot 即可全链路测试。

M3 说明：索引流程在 `llm/indexing.py`（版本化原子切换，无知识真空期）；检索在 `llm/rag.py`；无 `LLM_API_KEY` 时 embedder 为 None、索引任务明确失败（绝不用假向量污染知识库）；`DeterministicFakeEmbedder` 仅用于测试与 `--fake` 冒烟。评测：`uv run python scripts/eval_rag.py`（真实 key）或 `--fake`（离线管线冒烟）；评测集在 `scripts/eval/evalset.json`（当前 14 题，待扩到 30–50）。SQLAlchemy 坑：chunks 的 metadata 列映射属性名是 `meta`，insert values 必须用 `meta` 做键。

## 常用命令

```bash
# 基础设施（postgres:55432 + redis:6379；项目名 mercury，避免与本机其他 compose 项目冲突）
docker compose -f deploy/compose.yaml up -d

# Python（单一根 pyproject；导入名 api/worker/domain/llm/integrations/observability）
uv sync                                # 安装依赖
uv run alembic upgrade head            # 应用迁移（DATABASE_URL 默认指向 localhost:55432）
uv run uvicorn api.main:app --port 8000  # 启动 api；/health/live 与 /health/ready
uv run arq worker.main.WorkerSettings    # 启动 worker（消息管线 + 兜底扫描器 cron）
uv run python scripts/set_webhook.py     # 注册真实 bot webhook（需 .env 配好三件套）
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest -q                       # 集成测试需 DATABASE_URL/REDIS_URL（本地 compose 或 CI services），缺省自动 skip

# 单个测试
uv run pytest tests/unit/test_health.py -q

# Web（apps/web，Next.js 15 + AntD 5）
cd apps/web && pnpm install && pnpm dev   # 本地开发（/api 代理到 localhost:8000）
pnpm lint && pnpm typecheck && pnpm build
```

注意：本地 postgres 端口是 **55432**（5432 被本机其他项目占用）；生产/CI 用各自的 DATABASE_URL。migration 用 autogenerate 后必须人工校对（pgvector import、CREATE EXTENSION、表达式索引）。

## 规划中的架构（文档 §6）

模块化单体——刻意**不做**微服务化——使用 Docker Compose + Traefik 部署：

- `api` — Python 3.12 + FastAPI（uv 管理）：Telegram Webhook、后台 API、RAG、编排、线索逻辑。Telegram 用 aiogram 或 python-telegram-bot；Agent/RAG 用 LangGraph + LangChain。
- `worker` — 文档索引、CRM 同步、失败重试、摘要任务（基于 Redis 队列）。
- `web` — 管理后台：Next.js App Router + TypeScript + Ant Design。
- `postgres` — PostgreSQL 16 + pgvector，同时存业务数据和向量。
- `redis` — 队列、锁和短期状态。

模型调用通过 OpenAI 兼容接口抽象，不绑定单一 LLM 供应商。建议目录：`apps/{api,worker,web}`、`packages/{domain,llm,integrations,observability}`、`migrations/`、`tests/`、`deploy/`。

数据模型（users、conversations、messages、knowledge_documents、knowledge_chunks、leads、handoffs、integration_jobs、audit_logs）和 API 草案见文档 §7–8，命名以文档为准。

## 不可妥协的设计约束（文档 §4、§5、§9）

- **范围纪律**：试点客户确认前只做 P0 功能。本阶段明确不做：多渠道接入（WhatsApp/Discord/网站聊天）、多租户与计费、Mini App 商城、批量私聊/群成员抓取、自研通用 CRM、模型微调。
- **Webhook 幂等**：Telegram update 以 `update_id` 去重；重复推送绝不能产生重复消息或重复线索。
- **只做有依据的回答**：机器人只依据已启用的知识库文档回答业务事实，保留来源引用；检索证据不足时必须明确拒答并转人工。禁止编造价格、SLA、退款政策及法律/合同承诺。
- **确定性线索评分**：LLM 只负责提取结构化字段（经 Schema 校验）；评分由应用代码中可解释的规则完成，每次评分都要保存理由。
- **人工接管状态机**：会话状态为 `ai_active` → `handoff_pending` → `human_active` →（回到 `ai_active` 或 `closed`）。处于 `human_active` 时 AI 绝不能自动回复。状态正确率是 100% 的验收要求。
- **CRM / 表格同步**：异步任务 + 幂等键 + 失败重试 + 失败待处理队列——集成不可用时原始线索数据绝不丢失。
- **提示词注入防线**：用户消息和知识库文档内容一律是数据而不是指令，不能覆盖系统提示词。隐私、合同、安全、支付、投诉类问题优先转人工。
- **密钥与隐私**：Bot Token、模型 Key 只经环境变量/Secret 管理；日志对邮箱、Token 和敏感字段脱敏；支持按 Telegram user ID 查询和删除用户数据。

## 第一项开发任务（文档 §15）

在做管理后台、人工接管、CRM 之前，先完成最小纵向闭环并保证稳定：

> Telegram 收到消息 → 保存消息 → 从小型知识库检索 → 安全回答 → 提取线索字段 → 保存线索 → 返回 Telegram。

整个 MVP 的验收测试用例见文档 §10。
