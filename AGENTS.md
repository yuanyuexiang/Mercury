# 仓库指南

## 项目结构与模块组织

本仓库目前以设计文档为先：`docs/Telegram-AI-Lead-System-MVP.md` 定义产品范围，`docs/technical-design.md` 是实现依据。修改架构、数据表、状态或 API 名称前，必须先阅读对应章节。

规划中的模块化单体将 FastAPI 和 arq 入口分别放在 `apps/api/` 与 `apps/worker/`，Next.js 管理后台放在 `apps/web/`，共享 Python 代码放在 `packages/{domain,llm,integrations,observability}/`。数据库迁移、自动化脚本、部署配置和测试分别放在 `migrations/`、`scripts/`、`deploy/` 与 `tests/{unit,integration}/`。`domain` 包不得导入 FastAPI、arq 或 aiogram。

## 构建、测试与开发命令

当前尚无可执行脚手架。M1 落地后，应使用技术方案规定的命令，并让本指南与实际脚本保持同步：

- `uv sync`：安装 Python 工作区依赖。
- `uv run ruff check .` 和 `uv run ruff format --check .`：执行代码检查和格式验证。
- `uv run mypy .`：执行静态类型检查。
- `uv run pytest`：运行单元测试与集成测试。
- `pnpm --dir apps/web install` 和 `pnpm --dir apps/web build`：安装并构建管理后台。
- `docker compose -f deploy/compose.yaml up`：Compose 配置完成后启动依赖与应用服务。

## 编码风格与命名约定

Python 目标版本为 3.12，使用四空格缩进、完整类型注解、SQLAlchemy 异步 API 和 Ruff 格式化。Python 模块与函数使用 `snake_case`，类和 Pydantic 模型使用 `PascalCase`；集成边界采用显式依赖注入。TypeScript 组件使用 `PascalCase`，路由遵循 Next.js App Router 约定。表名、字段、枚举和状态必须沿用 `docs/technical-design.md`，不得另行创造名称。

## 测试指南

测试框架使用 pytest。测试文件命名为 `test_<行为>.py`，测试函数命名为 `test_<预期结果>`。评分、线索合并、人工接管状态迁移、文本切分和邮箱分类应使用无外部依赖的单元测试。集成测试使用 PostgreSQL、Redis 和 `FakeLLM`；CI 禁止依赖真实模型密钥。每项 MVP 验收用例都应对应一个具名测试。重点覆盖 Webhook 幂等性，以及 `human_active` 状态下 AI 不得回复的规则。

## 提交与 Pull Request 规范

仓库目前没有可供归纳的提交历史。提交标题应简短、使用祈使语气并标明范围，例如 `feat(worker): add idempotent update processing`。使用短期分支，且仅在 lint、类型检查、测试和构建全部通过后通过 PR 合并。PR 应说明变更内容，关联相关设计章节或 Issue，列出验证方式；UI 变更需附截图。严禁提交 `.env` 文件、Token、客户数据或模型凭据。
