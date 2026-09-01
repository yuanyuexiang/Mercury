# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

用户偏好中文，请使用中文与用户交流。

## 仓库现状

这是一个全新仓库，**目前还没有任何代码**。两份核心文档：

- [docs/Telegram-AI-Lead-System-MVP.md](docs/Telegram-AI-Lead-System-MVP.md) — 产品需求与边界的事实来源（其 §6 技术建议已被技术方案替代）：用企业知识库通过 RAG 回答客户问题，从对话中提取并评分销售线索，必要时转人工，并将线索同步到 CRM / Google Sheets。
- [docs/deployment.md](docs/deployment.md) — 部署手册：服务器初始化、GitHub secrets、首发与回滚、日常运维。
- [docs/technical-design.md](docs/technical-design.md) — **实现级技术方案（写代码以它为准）**：所有选型已定案（aiogram、arq、SQLAlchemy async、gspread、纯 Python 编排管线不用 LangGraph）、完整 DDL、编排管线、状态机、API 契约、环境变量清单，以及 M1–M8 实现里程碑顺序。

写任何代码前先读技术方案对应章节；表名、状态值、接口以技术方案为准，不即兴改名。新的设计决策要落回技术方案文档。

## 产品定位（技术方案 §20）

**产品化定制服务路线**：80% 标准内核 + 20% 配置面，每客户独立 Docker 实例（独立数据库），单一 main 分支；3–5 个付费客户后再决定 SaaS 化。核心表已含 `tenant_id`（migration 0005，独立实例阶段恒为 1，查询**不做**租户过滤）；每客户定制只走配置：`BRAND_NAME`/`BOT_TONE_HINT`（欢迎语与 RAG 提示词）、`SCORING_OVERRIDES`（评分 JSON 覆盖，`domain/scoring.py::config_from_json`）、后台模型配置与知识库、`LeadSync` 端口换 CRM 实现。**红线：代码里禁止出现客户名称、客户分支、客户专属 if。** SaaS 化转换清单见 §20.4（含 telegram_updates PK 改造），现在不做。

## 当前进度

**M1–M8 完成，并通过第三轮外部评审修订**（技术方案 v1.4，2026-08-30）。修订要点：api/worker 共享 storage volume；`.dockerignore`（两镜像均实测构建通过）；webhook 数据库未落库返回 503 让 Telegram 重推（落库后入队失败才返回 200 交扫描器）；SSRF 抓取逐跳校验（`integrations/netguard.py`）；`messages.source_update_id` 外键 SET NULL（migration 0003，保留期清理不再被阻断）；用户数据删除 API `DELETE /api/users/by-telegram/{id}`；extract_lead 原子抢占（replied→extracting，扫描器③'恢复）；同 chat 顺序守卫（更早未完成 update 让位）；生产安全底线（https 环境启动强制校验 JWT/凭据，JWT 校验 sub）；删文档同时删原始文件。剩余为运营侧工作（配真实凭据跑演示验收剧本、录 Demo、客户清单）。

M8 说明：后台 API 全量在 `apps/api/routers/`（认证 cookie JWT + bcrypt + 登录限流；写接口需 `X-Requested-With: fetch` CSRF 头）；供应商配置在 `llm/provider_config.py`——Fernet 加密（主密钥 `SETTINGS_ENCRYPTION_KEY`，生成：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`）、DB 优先 env 兜底、60s 缓存 + Redis 广播失效，worker 用 `DynamicChatClient` 每次调用解析配置（切换供应商不重启即生效）；SSRF 防护在 `api/netguard.py`（自建推理服务用 `ALLOW_PRIVATE_LLM_BASE_URL=true` 放开）。LLM 全量后台可配（含 embedding，`DynamicEmbedder` + 1536 维守卫）；env 的 LLM_* 仅为兜底。双槽位模型配置（2026-08-31，migration 0009）：服务商行只管凭据，`is_active`=对话槽、`is_embed_active`=检索槽（各 partial unique），可不同家（智谱对话 + 硅基检索）；指派走 `PUT /api/settings/llm-providers/roles/{chat|embed}`；`get_embed()` 解析检索槽行 → env 兜底；担任槽位的行不可删。embedding 请求带 `dimensions=1536`（Matryoshka 模型如 Qwen3-Embedding 按需输出 1536 维，上游不支持该参数则自动降级）；「测试」只测该行实际承担的用途（对话/检索/仅连通性），检索测试含维度校验；在用服务商也可删除（删除即腾空槽位+广播，前端弹窗说明后果）。设置页为微信式工作台（与会话页同构）：左栏服务商列表（置顶「当前生效」，`?id=` 深链）+ 内容区（总览两张槽位卡 / 服务商详情含密钥管理与「设为对话/检索」配置块）；进入详情自动拉模型列表并分类分流（`web/src/lib/providers.ts::classifyModels`，embedding 关键词→检索下拉、语音图像 rerank 进「其他」、其余→对话下拉）+ 空输入自动预填推荐 + 保存自动实测。供应商填表零查询：前端内置预设表（`web/src/lib/providers.ts`，选择即填 base_url/推荐模型/key 直达链接），`POST /api/settings/llm-providers/models` 拉取 `{base_url}/models` 供下拉选择（app.state.list_models 可打桩）。前端在 `apps/web/src/app/`（AntD 5 + React 19 补丁包）；获客驾驶舱式概览（漏斗/今日/趋势/最新高意向）、会话页为三栏 IM 工作台（列表/聊天/线索画像，`?id=` 深链，旧 `/conversations/{id}` 重定向兼容）、全局侧边栏为微信式 64px 窄图标栏（Tooltip 显示名称，会话图标挂待接管 badge，30s 轮询 `/api/metrics/pending`）、线索页等级 Tab + CSV 导出（`/api/leads/export`）、品牌白标走免认证 `/api/meta`（BRAND_NAME，见 §20）。渠道归因（migration 0006）：`/start` 深链参数首触写 `conversations.source_channel` → 线索继承 → Sheets Channel 列 / CSV 渠道列 / 概览渠道表；漏斗含「已成交」级（`lead.status=won`）。系统设置后台化（migration 0007，`app_settings` KV 表 + `integrations/app_settings.py::AppSettingsStore`，DB 优先 env 兜底、token Fernet 加密、60s 缓存 + Redis 广播）：Telegram Bot Token/通知 Chat ID/品牌/语气全部在后台「系统设置」页配置，保存自动 getMe 验证 + 注册 webhook；发送走 `DynamicSender`（token 热切换）。客户引导：系统设置页为三步接入向导，Chat ID 走「检测最近联系人」（`/api/settings/telegram/candidates`，从 webhook 流量提取候选，无需 getUpdates）；概览页有「快速开始」四步清单（`/api/settings/setup-status`，全绿自动隐藏）。「推广获客」页（`/promotion`）：渠道深链生成器 + AntD QRCode 二维码下载 + 可复制引流话术 + 各触点效果表（复用 overview.channels）——引流物料工具，纯前端无新后端；主动群发/抓群成员是红线不做。沉睡线索唤醒（migration 0008，技术方案 §11.5）：每日 cron UTC 02:30 对安静 ≥3 天的 open 中高意向 + ai_active 会话发确定性跟进文案（`texts.revive_follow_up`，不走 LLM），`revive_count` 持久防重（默认至多 1 次），开关/天数/次数在后台「系统设置 → 自动跟进」配置（`GET/PUT /api/settings/revive`，env 仅兜底）。会话页与线索页均为三栏工作台（列表/详情/上下文，`?id=` 深链，旧 `/leads/{id}` 重定向兼容）。部署：`deploy/compose.prod.yaml`（接既有 Traefik、migrate 一次性服务、每日备份保留 14 份）+ `deploy/deploy.sh`（健康检查失败自动回滚上一 tag）+ `.github/workflows/cd.yml`（push main → GHCR → SSH；回滚 = workflow_dispatch 填历史 sha-* tag；提速设计：ci 与 build 并行、deploy 双依赖，web 在 runner 上 pnpm build（.next/cache 增量缓存）后用 `Dockerfile.web-prebuilt` 仅拷贝打镜像——组装产物必须 `cp -a` 保留 pnpm 符号链接；push 时 ci 的 web job 不再重复 build，仅 PR 构建验证）。服务器初始化：`~/mercury/`（实际服务器为 `/home/ubuntu/mercury/`，cd.yml 用 `cd ~/mercury`）放 compose.prod.yaml + deploy.sh + .env，GitHub secrets 配 DEPLOY_HOST/USER/SSH_KEY。

M7 说明：`run_sync_lead` 原子抢占（pending→running）→ 从 DB 读**最新** lead 组装行（payload 仅审计快照，乱序无害）→ LLM 摘要（失败不阻塞）→ `LeadSync` 端口 upsert → done + 回填 external_crm_id/status=synced；失败退避 2^attempts 分钟回 pending，≥5 次置 failed 并通知。gspread 实现在 `integrations/sheets.py`（按 Lead ID 列找行、to_thread 包同步库）；凭据未配置时任务走 retry 路径（配好即恢复）。扫描器④（running 超时重置 + pending 入队丢失补偿）已实装。**真实 Google Sheet 验证需要 Service Account**：`.env` 配 `GOOGLE_SERVICE_ACCOUNT_JSON`（路径或 base64）+ `LEADS_SPREADSHEET_ID`，并把表共享给 service account 邮箱。

M6 说明：状态机在 `domain/handoff.py`——纯函数迁移表 `next_status()` + 唯一变更入口 `transition()`（非法迁移抛 HandoffError，变更写 audit）；静默型触发（user_request/sensitive/manual）→ handoff_pending，通知型（low_confidence/high_intent）创建即 resolved 不改状态；/human 幂等；静默态下非文本消息也只转通知不回"仅支持文字"。管理端 accept/resume_ai/close 的 API 在 M8 挂接（直接调 transition）。坑：structlog 的 kwarg 不能叫 `event`（与事件名参数冲突）。

M5 说明：管线出现购买意图（或已有 lead）→ update 标 `replied` + 入队 `extract_lead` 独立任务（提取→合并→评分→追问→高意向通知→版本化同步任务行）；评分/合并是纯函数（`domain/scoring.py`/`lead_merge.py`），LLM 只输出事实（含 asked_demo_or_quote/freebie_only 两个事实布尔，migration 0002 加了对应列）；追问有代码层兜底——关键字段全被填/拒后即使 LLM 给了问题也不发。integration_jobs 行已创建但 sync_lead 的 enqueue 留给 M7（TODO 标注）。注意 ORM UPDATE 会同步内存对象，版本号必须先算后用（见 run_extract_lead 注释）。

M4 说明：LLM 依赖经 `Brain` 协议注入编排层（实现在 `llm/brain.py`，测试用 conftest 的 FakeBrain）；提示词全部在 `llm/prompts.py`（拒答用 NO_ANSWER_MARKER 哨兵）；端到端预算 `Deadline` 在 `domain/schemas.py`（triage 上限 2s 计入总预算，RAG 拿剩余）；chat 客户端双档策略——用户路径不重试不切 fallback，非用户路径重试1次+fallback。**真实模型验收**：配好 `.env`（LLM_API_KEY/LLM_CHAT_MODEL）后跑 `uv run python scripts/eval_rag.py --with-answers`，看"生成级报告"两个指标。

文案本地化（2026-09-01）：`domain/texts.py` 全部客户可见固定文案改为按客户语言输出函数（`refused_no_answer(lang)` 等；lang = triage 识别优先、Telegram `language_code` 兜底，"auto"/空默认中文），不再中英堆叠；文案纪律：不暴露内部概念（知识库/资料）、拒答语气"接住"不"推开"；`revive_follow_up` 刻意保持双语（沉睡客户语言不确定）。购买意向拒答改道（同日）：triage `purchase_intent=True` 且 RAG 拒答时走 `texts.purchase_ack`（确认+引导补充信息）而非拒答文案，不记 low_confidence、通知文案为"客户表达购买意向"，仍入 extract_lead；RAG 提示词补充规则——意向表态且材料覆盖时热情推进而非输出哨兵。

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
