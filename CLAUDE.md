# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

用户偏好中文，请使用中文与用户交流。

## 仓库现状

这是一个全新仓库，**目前还没有任何代码**。两份核心文档：

- [docs/Telegram-AI-Lead-System-MVP.md](docs/Telegram-AI-Lead-System-MVP.md) — 产品需求与边界的事实来源（其 §6 技术建议已被技术方案替代）：用企业知识库通过 RAG 回答客户问题，从对话中提取并评分销售线索，必要时转人工，并将线索同步到 CRM / Google Sheets。
- [docs/technical-design.md](docs/technical-design.md) — **实现级技术方案（写代码以它为准）**：所有选型已定案（aiogram、arq、SQLAlchemy async、gspread、纯 Python 编排管线不用 LangGraph）、完整 DDL、编排管线、状态机、API 契约、环境变量清单，以及 M1–M8 实现里程碑顺序。

写任何代码前先读技术方案对应章节；表名、状态值、接口以技术方案为准，不即兴改名。新的设计决策要落回技术方案文档。等脚手架落地后，更新本文件补充真实的构建 / 测试 / 运行命令。

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
