# Telegram AI 客服与询盘转化系统

## 产品与 MVP 开发文档 v0.1

- 文档日期：2026-08-28
- 产品阶段：市场验证 / 可销售 MVP
- 目标客户：已经使用 Telegram 承接客户咨询的海外 AI SaaS、API、开发者工具团队
- 产品类型：先做可定制交付的服务，验证后再决定是否 SaaS 化

> **实现说明（2026-08-29）**：本文档是需求与商业边界的事实来源；§6 技术架构仅为初始建议，实现级决策以 [technical-design.md](./technical-design.md) 为准（已定案的差异包括：不用 LangGraph、LLM 管线全部在 worker 执行、CRM 首选 Google Sheets、编排为纯 Python 显式管线等）。两者冲突时以技术方案为准。

---

## 1. 项目结论与边界

### 1.1 产品定义

本产品不是普通 FAQ 机器人，而是一套 **Telegram 询盘自动转化系统**：

> 使用企业现有文档回答客户问题，识别潜在采购需求，收集关键字段，对线索评分，将高意向客户同步给销售人员和 CRM。

英文一句话定位：

> Turn Telegram conversations into qualified sales leads — automatically.

### 1.2 已确认事实

- Telegram Bot API 能够接收消息、回复消息、使用 Webhook 并连接外部业务系统。
- Telegram 支持 Business Bot、Mini App、支付、订阅和人工参与等扩展能力。
- 市场上已有 Telegram 客服、CRM 集成和 AI Agent 产品。
- 公开外包市场存在 Telegram + AI + CRM 的开发需求。
- 当前团队具备 Bot、RAG、Agent、CRM、Next.js、Python、Docker 和 DevOps 交付能力。

### 1.3 待验证假设

- 目标客户是否愿意为单渠道 Telegram 方案付费。
- 试点价格是否可以达到 500–1,000 美元。
- 商业版本是否可以达到 2,000–5,000 美元。
- 客户是否普遍要求同时接入 WhatsApp、网站和邮件。
- 定制交付的利润是否高于获客及维护成本。

### 1.4 当前决策

- 先开发一套可演示、可部署、可定制的 MVP。
- 不先开发完整多租户 SaaS。
- 不以“机器人功能数量”为卖点，以响应速度、线索质量和漏单减少为卖点。
- MVP 完成后立即进行真实客户验证，避免持续闭门开发。

---

## 2. 目标客户与使用场景

### 2.1 理想客户画像 ICP

必须满足：

- 企业官网或产品页面公开展示 Telegram 入口。
- Telegram 是其客户咨询或社群支持的重要渠道。
- 每月约 300 条以上有效咨询，或至少有 2 名客服/运营人员。
- 群组或私聊中存在重复问题、回复延迟、询盘遗漏。
- 企业有明确收费产品，而非纯免费社区。
- 可以找到 Founder、Head of Growth、Support Lead、Community Manager 或 RevOps 负责人。

优先行业：

1. AI SaaS、API 与开发者工具。
2. Web3 基础设施、钱包和合规技术服务。
3. Telegram Mini App 与海外游戏团队。
4. 海外教育、付费会员和专业社群。
5. 跨境物流、采购和 B2B 贸易服务。

明确排除：

- 博彩、诈骗、荐股、无资质金融带单。
- 需要抓取群成员并批量骚扰的客户。
- 要求绕过 Telegram 限制或伪装真人群发的客户。
- 无明确产品、无客服流量、只想“装机器人自动获客”的客户。

### 2.2 核心场景

客户进入 Telegram 后：

1. 询问产品、功能、价格、部署或 API 问题。
2. AI 根据企业知识库生成有依据的回答。
3. 系统从对话中识别公司、团队规模、需求、预算和采购时间。
4. 缺少关键字段时，AI 自然追问，不使用生硬表单轰炸用户。
5. 系统计算线索分数并划分意向等级。
6. 高意向或敏感问题立即通知人工客服。
7. 人工接管后，AI 停止自动回复。
8. 线索及对话摘要写入 CRM 或 Google Sheets。
9. 后台展示咨询量、自动解决率、线索量和人工接管率。

---

## 3. MVP 目标与成功指标

### 3.1 MVP 业务目标

- 形成一段 60–90 秒可用于营销的完整演示。
- 能在 7 天内为一个试点客户完成知识库配置和部署。
- 证明系统能够把 Telegram 对话转成结构化销售线索。
- 获取至少 1 个 500 美元以上的付费试点。

### 3.2 产品指标

| 指标 | MVP 目标 |
|---|---:|
| 首次自动响应时间 | 小于 5 秒（不含模型异常） |
| 有依据问题的正确回答率 | 测试集达到 85% 以上 |
| 无依据问题安全拒答率 | 95% 以上 |
| 线索字段提取准确率 | 90% 以上 |
| 人工接管状态正确率 | 100% |
| CRM/表格同步成功率 | 99% 以上，可重试 |
| 消息处理可追踪率 | 100% 有日志和状态 |

以上为内部验收目标，不作为未经验证的对外营销承诺。

### 3.3 市场验证指标

| 指标 | 首轮目标 |
|---|---:|
| 精准目标企业 | 20 家 |
| 个性化诊断 | 5 份 |
| 有效回复 | 至少 3 个 |
| 产品演示 | 至少 2 次 |
| 付费试点 | 至少 1 个 |

若无人愿意付费，则暂停扩展功能，重新判断客户、价值主张、价格或是否转向多渠道方案。

---

## 4. MVP 功能范围

### 4.1 P0：首版必须实现

#### Telegram 接入

- BotFather 创建机器人并配置 Webhook。
- 支持私聊文本消息。
- 支持 `/start`、隐私说明、重新开始和联系人工。
- 保存 Telegram user ID、chat ID、用户名、语言及消息时间。
- Webhook 更新幂等处理，避免重复消费。

#### AI 知识库问答

- 导入 Markdown、TXT、PDF 或网页文本。
- 文档切分、向量化和检索。
- 回答中保留内部来源引用，后台可追溯。
- 检索证据不足时明确表示无法确认，并建议人工处理。
- 禁止模型自行编造价格、合同承诺、退款政策和安全结论。

#### 线索识别与采集

- 自动判断当前对话是否存在购买意图。
- 提取并持续更新以下字段：
  - 姓名
  - 公司名称
  - 国家/地区
  - 工作邮箱
  - 产品需求
  - 团队规模
  - 预算范围
  - 采购时间
  - 期望集成
  - 备注
- 字段缺失时，根据上下文最多追问一个关键问题。
- 用户明确拒绝提供信息后不重复追问。

#### 线索评分

MVP 使用可解释规则，不直接依赖不可控的黑盒评分：

| 条件 | 分数 |
|---|---:|
| 使用公司邮箱 | +15 |
| 明确产品需求 | +20 |
| 团队规模达到目标客户标准 | +15 |
| 给出预算 | +15 |
| 采购时间在 30 天内 | +20 |
| 主动要求 Demo/报价 | +25 |
| 仅求免费资源或无关咨询 | -20 |

- 0–29：低意向
- 30–59：中意向
- 60 以上：高意向

后续可以按客户业务配置权重。

#### 人工接管

- 用户可以点击“Talk to a human”。
- 高意向、投诉、安全、退款、合同和模型低置信度自动触发人工提醒。
- 人工接管后会话状态切换为 `human_active`，AI 不再自动回复。
- 人工可以恢复 AI 接待。
- 系统记录接管人、接管时间及原因。

#### CRM / 表格同步

- MVP 首选 Google Sheets 或 Twenty CRM，二选一完成首个演示。
- 创建或更新联系人与线索。
- 写入 Telegram 身份、字段、分数、意向等级、摘要及最后联系时间。
- 同步采用异步任务、幂等键与失败重试。
- 同步失败进入待处理列表，不丢失原始消息。

#### 管理后台

- 管理员登录。
- 会话列表、搜索和状态筛选。
- 查看完整对话、AI回答来源、线索字段和评分理由。
- 人工接管/恢复 AI。
- 知识库文档上传、启用、停用和重新索引。
- 基础指标：消息数、会话数、自动回复数、人工接管数、有效线索数。

#### 运维与审计

- 健康检查。
- 结构化日志及 request/trace ID。
- 模型调用耗时、Token 和成本记录。
- Webhook、模型、数据库和 CRM 错误分类。
- 敏感配置仅通过环境变量或 Secret 管理。

### 4.2 P1：试点客户确认后实现

- Telegram Business Bot 账号模式。
- HubSpot CRM 正式集成。
- 群组 @Bot 场景。
- 英文以外的自动识别和多语言回复。
- 语音消息转写。
- 图片/OCR理解。
- 预约 Calendly/Google Calendar。
- 每日销售与客服摘要。
- UTM/deep link 来源追踪。
- 多知识库和不同机器人配置。

### 4.3 本阶段明确不做

- WhatsApp、Instagram、Discord、网站聊天等多渠道接入。
- 完整多租户、套餐、订阅计费和用量账单。
- Telegram Mini App 商城或复杂前端。
- 数字商品支付和 Telegram Stars。
- 自动外呼、批量私聊、群成员抓取。
- 复杂营销自动化和群发系统。
- 自研通用 CRM。
- 模型微调。

---

## 5. 核心交互流程

### 5.1 正常问答与线索生成

1. Telegram 将 update 推送到 Webhook。
2. API 校验并以 `update_id` 做幂等。
3. 保存用户消息。
4. 编排器判断：人工状态、风险类型、购买意图、是否需要 RAG。
5. 检索知识库并生成受约束回复。
6. 提取或更新线索字段。
7. 重新计算线索分数。
8. 保存 AI 回复、来源、Token、耗时和评分理由。
9. 向 Telegram 发送回复。
10. 高意向时通知人工并提交 CRM 同步任务。

### 5.2 无答案处理

- 检索分数不足或证据冲突时，不生成确定性答案。
- 回复用户“我目前无法从官方资料中确认”。
- 收集必要背景并触发人工处理。
- 后台标记为知识库缺口，供管理员补充文档。

### 5.3 人工接管

- 触发条件：用户请求、低置信度、敏感问题、高价值线索或管理员主动接管。
- 状态由 `ai_active` 变为 `handoff_pending`，确认接管后为 `human_active`。
- 人工处理完成后可切换为 `ai_active`。

---

## 6. 建议技术架构

### 6.1 技术选型

- 后端：Python 3.12 + FastAPI + uv
- Telegram：aiogram 或 python-telegram-bot
- Agent/RAG：LangGraph + LangChain
- 数据库：PostgreSQL 16 + pgvector
- 缓存/轻量任务：Redis
- 后台：Next.js App Router + TypeScript + Ant Design
- 对象存储：首版可使用本地 volume；试点后切换 MinIO/S3
- 模型：通过 OpenAI 兼容接口抽象，避免绑定单一供应商
- 部署：Docker Compose + Traefik
- 可观测性：结构化日志；后续接 Loki/Grafana/OpenTelemetry

### 6.2 服务划分

MVP 不做过度微服务化：

- `api`：Webhook、后台 API、RAG、编排、线索逻辑。
- `worker`：文档索引、CRM 同步、失败重试和摘要任务。
- `web`：管理后台。
- `postgres`：业务数据和向量。
- `redis`：队列、锁和短期状态。

代码采用模块化单体，待真实负载和团队扩大后再拆分服务。

### 6.3 建议目录

```text
telegram-lead-ai/
├── apps/
│   ├── api/
│   ├── worker/
│   └── web/
├── packages/
│   ├── domain/
│   ├── llm/
│   ├── integrations/
│   └── observability/
├── migrations/
├── tests/
├── deploy/
│   ├── compose.yaml
│   └── traefik/
├── docs/
├── .env.example
└── README.md
```

---

## 7. 数据模型

### 7.1 主要实体

#### users

- id
- telegram_user_id（唯一）
- username
- first_name
- last_name
- language_code
- consent_status
- created_at / updated_at

#### conversations

- id
- telegram_chat_id
- user_id
- status：`ai_active` / `handoff_pending` / `human_active` / `closed`
- assigned_operator_id
- started_at / last_message_at / closed_at

#### messages

- id
- conversation_id
- telegram_message_id
- direction：`inbound` / `outbound`
- sender_type：`user` / `ai` / `operator` / `system`
- content
- content_type
- model_name
- prompt_tokens / completion_tokens
- latency_ms
- confidence
- created_at

#### knowledge_documents

- id
- title
- source_type
- source_url
- storage_path
- checksum
- status
- version
- created_at / updated_at

#### knowledge_chunks

- id
- document_id
- chunk_index
- content
- metadata JSONB
- embedding vector

#### leads

- id
- user_id
- conversation_id
- name
- company
- country
- business_email
- requirement
- team_size
- budget_range
- purchase_timeline
- integrations JSONB
- score
- grade
- score_reasons JSONB
- status
- external_crm_id
- created_at / updated_at

#### handoffs

- id
- conversation_id
- reason
- requested_at
- accepted_at
- resolved_at
- operator_id

#### integration_jobs

- id
- integration_type
- entity_type
- entity_id
- idempotency_key
- payload JSONB
- status
- attempts
- last_error
- next_retry_at

#### audit_logs

- id
- actor_type / actor_id
- action
- entity_type / entity_id
- metadata JSONB
- created_at

---

## 8. API 草案

### Telegram

- `POST /webhooks/telegram/{bot_secret}`
- `GET /health/live`
- `GET /health/ready`

### 会话

- `GET /api/conversations`
- `GET /api/conversations/{id}`
- `POST /api/conversations/{id}/handoff`
- `POST /api/conversations/{id}/resume-ai`
- `POST /api/conversations/{id}/messages`

### 线索

- `GET /api/leads`
- `GET /api/leads/{id}`
- `PATCH /api/leads/{id}`
- `POST /api/leads/{id}/sync`

### 知识库

- `POST /api/knowledge/documents`
- `GET /api/knowledge/documents`
- `PATCH /api/knowledge/documents/{id}`
- `POST /api/knowledge/documents/{id}/reindex`
- `DELETE /api/knowledge/documents/{id}`

### 指标

- `GET /api/metrics/overview`
- `GET /api/metrics/costs`
- `GET /api/metrics/knowledge-gaps`

---

## 9. AI 编排与安全规则

### 9.1 编排原则

- FAQ 可直接 RAG 回答，不需要把所有请求都做成复杂多 Agent。
- 字段提取使用结构化输出和 Schema 校验。
- 线索评分由确定性规则完成，LLM 只负责提取事实。
- 所有外部写操作必须经过应用代码校验，而不是让模型直接任意调用。
- 模型失败时返回安全提示并转人工，不阻塞 Webhook。

### 9.2 回答约束

- 只依据启用的企业资料回答关键业务事实。
- 不虚构功能、价格、折扣、SLA、退款或法律承诺。
- 对提示词注入内容按普通用户数据处理，不能修改系统规则。
- 知识库文档中的指令性文本不能覆盖系统提示词。
- 对隐私、合同、安全、支付和投诉问题优先转人工。

### 9.3 数据与隐私

- 首次交互提供简短隐私提示。
- 仅收集完成销售或支持所必需的信息。
- 不保存 Bot Token、模型 Key 等秘密到数据库明文字段或日志。
- 日志对邮箱、Token 和敏感字段脱敏。
- 支持按 Telegram user ID 查询和删除用户数据。
- 为客户配置数据保留期限。

---

## 10. 验收测试

### 10.1 必测用例

- 相同 Telegram update 重复推送不会产生重复消息或线索。
- 用户连续提问时不会重复追问已经获得的字段。
- 知识库有明确答案时能够正确回答并记录来源。
- 知识库无答案时不会编造。
- 用户要求人工后，AI 立即停止自动回复。
- 人工恢复 AI 后状态正确。
- 高意向条件正确计分并说明理由。
- CRM 暂时不可用时任务重试，原始线索不丢失。
- 模型超时或限流时返回可理解提示。
- 恶意提示词无法获取系统提示、密钥或其他用户信息。
- 不同会话数据严格隔离。

### 10.2 演示验收剧本

虚拟产品采用“企业 AI API/SaaS”场景。演示用户依次询问：

1. 是否支持私有化部署。
2. 是否可以集成 HubSpot。
3. 50 人团队的价格范围。
4. 希望下周安排 Demo。

系统必须展示：知识回答 → 需求追问 → 字段提取 → 高意向评分 → CRM 入库 → 人工通知。

---

## 11. 两周开发计划

### 第 1–2 天：基础工程

- 建立仓库、Docker Compose、FastAPI、Next.js、PostgreSQL、Redis。
- 配置数据库迁移、环境变量、日志和健康检查。
- 完成 Telegram Webhook 与消息收发。

### 第 3–4 天：知识库

- 完成文档导入、切分、Embedding、pgvector 检索。
- 建立受约束的 RAG 回答链。
- 准备 30–50 个问题的评测集。

### 第 5–6 天：线索模块

- 完成结构化字段提取、字段合并和评分规则。
- 完成高意向判断和人工提醒。

### 第 7–8 天：管理后台

- 会话列表、详情、线索信息、评分理由。
- 人工接管与恢复 AI。
- 知识库上传和状态管理。

### 第 9 天：外部同步

- Google Sheets 或 Twenty CRM 集成。
- 实现幂等、重试和失败状态。

### 第 10–11 天：安全与测试

- 提示词注入、越权、日志脱敏和异常路径测试。
- 完成核心集成测试和演示脚本测试。

### 第 12 天：部署

- 使用 Docker Compose + Traefik 部署演示环境。
- 配置 HTTPS、备份和基础监控。

### 第 13–14 天：销售材料

- 录制 60–90 秒英文 Demo。
- 完成英文落地页核心文案。
- 制作 Telegram 客服审计模板。
- 建立 20 家首批目标客户清单并开始验证。

---

## 12. 商业包装

### 12.1 试点产品

建议名称：Telegram AI Lead Pilot

包含：

- 1 个 Telegram Bot。
- 1 套企业知识库。
- AI FAQ 与安全转人工。
- 最多 10 个线索字段。
- 1 个 Google Sheets 或 CRM 集成。
- 基础会话与线索后台。
- 7 天部署与 14 天观察期。

建议试点价格：500–1,000 美元。首个案例可以采用价格下限，但必须付费。

### 12.2 商业版

增加 HubSpot、多语言、语音/图片、预约、团队权限、分析和私有化部署后，建议项目价格 2,000–5,000 美元，并收取 200–800 美元/月的托管维护费。

价格仅为待验证假设，不写入对外固定承诺。

---

## 13. 风险与止损条件

| 风险 | 应对方式 |
|---|---|
| 客户认为现成 SaaS 足够 | 聚焦私有化、业务定制、CRM 深度集成和交付服务 |
| Telegram 单渠道市场过窄 | 在得到明确需求后扩展 WhatsApp 和网站聊天 |
| AI 幻觉造成错误承诺 | 有依据回答、敏感问题转人工、来源与审计 |
| 低价外包竞争 | 不卖 Bot 工时，卖询盘转化和运营结果 |
| 客户没有现成流量 | 在销售资格审查阶段排除 |
| 维护成本过高 | 模块化配置、标准部署、限制试点范围 |
| 合规或声誉风险 | 拒绝灰黑产、骚扰营销和绕过平台限制 |

止损条件：

- 完成可用 Demo 后，接触 20 家精准企业仍无 2 次有效演示。
- 进行 5 次有效演示后，无客户愿意支付 500 美元试点。
- 多数客户明确表示只需要现成低价 SaaS，且不存在定制集成需求。

满足止损条件时，不继续增加功能，转向客户定位调整或多渠道询盘系统。

---

## 14. 开发启动清单

- [ ] 确定项目英文名称和仓库名。
- [ ] 创建测试 Telegram Bot。
- [ ] 准备虚拟 AI SaaS 产品资料。
- [ ] 建立 30–50 个标准问答评测集。
- [ ] 决定首个同步目标：Google Sheets 或 Twenty CRM。
- [ ] 确定首个模型及备用模型。
- [ ] 初始化 PostgreSQL + pgvector。
- [ ] 完成 Webhook 幂等设计。
- [ ] 定义 lead JSON Schema。
- [ ] 定义人工接管状态机。
- [ ] 编写核心验收测试。
- [ ] 部署演示环境。
- [ ] 录制英文 Demo。
- [ ] 开始 20 家客户验证。

## 15. 第一项开发任务

第一项任务不是管理后台，而是完成最小纵向闭环：

> Telegram 收到一条消息 → 保存消息 → 从小型知识库检索 → 安全回答 → 提取线索字段 → 保存线索 → 返回 Telegram。

只有该闭环稳定后，再开发人工接管、CRM 和管理后台。
