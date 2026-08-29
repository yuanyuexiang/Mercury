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

    # 运行
    log_level: str = "INFO"
    data_retention_days: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
