"""应用配置：环境变量清单见技术方案 §13。所有进程（api/worker）共用。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    operator_telegram_chat_id: str = ""

    # LLM（OpenAI 兼容，env 为兜底配置，见 §12）
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    settings_encryption_key: str = ""
    llm_chat_model: str = ""
    llm_chat_model_fallback: str = ""
    llm_embed_model: str = "text-embedding-3-small"
    allow_private_llm_base_url: bool = False
    rag_min_similarity: float = 0.60
    rag_top_k: int = 6
    reply_deadline_s: float = 5.0
    # triage 单独上限（计入总预算）：默认 2s 适配快模型；DeepSeek-V3 等出 JSON 慢的调到 4–5
    triage_timeout_s: float = 2.0

    # 数据
    database_url: str = "postgresql+asyncpg://mercury:mercury@localhost:55432/mercury"
    redis_url: str = "redis://localhost:6379/0"

    # 后台
    admin_username: str = ""
    admin_password_hash: str = ""
    jwt_secret: str = ""
    public_base_url: str = ""

    # Google Sheets
    google_service_account_json: str = ""
    leads_spreadsheet_id: str = ""

    # 客户实例定制（§20 产品化定制：20% 配置面）
    brand_name: str = ""  # 品牌名，注入欢迎语与 RAG 提示词；空 = 通用称呼
    bot_tone_hint: str = ""  # 回复语气提示，如 "Friendly and concise, use emojis sparingly"
    scoring_overrides: str = ""  # 评分规则覆盖 JSON，见 domain/scoring.py config_from_json

    # 沉睡线索唤醒的兜底默认——实际配置在后台「系统设置」（app_settings，DB 优先）
    revive_enabled: bool = True
    revive_after_days: int = 3
    revive_max_attempts: int = 1

    # 运行
    log_level: str = "INFO"
    data_retention_days: int = 180
    storage_dir: str = "var/storage"  # 知识库原始文件存放目录（§6.1：首版本地 volume）


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_production_settings(settings: Settings) -> None:
    """生产安全底线（§14，第三轮评审）：PUBLIC_BASE_URL 为 https 即视为生产，启动即拒绝弱配置。"""
    if not settings.public_base_url.startswith("https"):
        return
    problems: list[str] = []
    if len(settings.jwt_secret) < 32:
        problems.append("JWT_SECRET 至少 32 字符")
    if not settings.admin_username or not settings.admin_password_hash:
        problems.append("管理员用户名与 bcrypt hash 必须配置")
    if not settings.settings_encryption_key:
        problems.append("SETTINGS_ENCRYPTION_KEY 未配置")
    if len(settings.telegram_webhook_secret) < 32:
        problems.append("TELEGRAM_WEBHOOK_SECRET 至少 32 字符")
    if problems:
        raise RuntimeError("生产配置不安全，拒绝启动：" + "；".join(problems))
