"""供应商配置（技术方案 §12）：DbConfigSource + Fernet 加密 + 热切换。

解析优先级：DB 激活供应商（llm_providers.is_active）→ env 兜底 → None。
进程内缓存 60s；激活/修改时 api 发布 Redis 失效广播，worker 订阅后立即清缓存——
后台切换供应商 worker 不重启即生效（M8 验收项）。
api_key 只以 Fernet 密文存库（主密钥 SETTINGS_ENCRYPTION_KEY 仅在 env）。
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass

import structlog
from cryptography.fernet import Fernet
from domain.config import Settings
from domain.models import LlmProvider
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()

PROVIDER_INVALIDATE_CHANNEL = "mercury:llm_provider_changed"
CACHE_TTL_S = 60.0


class ProviderNotConfigured(Exception):
    """既无 DB 激活供应商也无 env 兜底配置。"""


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    chat_model: str
    fallback_model: str = ""
    supports_json_schema: bool = True
    source: str = "env"  # env|db，日志与后台展示用


def _fernet(settings: Settings) -> Fernet:
    if not settings.settings_encryption_key:
        raise RuntimeError("缺少 SETTINGS_ENCRYPTION_KEY（Fernet 主密钥）")
    return Fernet(settings.settings_encryption_key.encode())


def encrypt_api_key(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt_api_key(settings: Settings, ciphertext: str) -> str:
    return _fernet(settings).decrypt(ciphertext.encode()).decode()


def mask_api_key(plaintext_or_any: str) -> str:
    tail = plaintext_or_any[-4:] if len(plaintext_or_any) >= 4 else "****"
    return f"****{tail}"


def env_provider(settings: Settings) -> ProviderConfig | None:
    if settings.llm_api_key and settings.llm_chat_model:
        return ProviderConfig(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            chat_model=settings.llm_chat_model,
            fallback_model=settings.llm_chat_model_fallback,
            source="env",
        )
    return None


class ProviderSource:
    """DB 优先、env 兜底的配置源；60s TTL + Redis 广播失效。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._settings = settings
        self._cache: ProviderConfig | None = None
        self._cached_at = 0.0
        self._listener_task: asyncio.Task[None] | None = None

    async def get(self) -> ProviderConfig | None:
        if self._cache is not None and (time.monotonic() - self._cached_at) < CACHE_TTL_S:
            return self._cache
        config = await self._load()
        self._cache = config
        self._cached_at = time.monotonic()
        return config

    def invalidate(self) -> None:
        self._cache = None
        self._cached_at = 0.0

    async def _load(self) -> ProviderConfig | None:
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(select(LlmProvider).where(LlmProvider.is_active))
                ).scalar_one_or_none()
            if row is not None:
                return ProviderConfig(
                    base_url=row.base_url,
                    api_key=decrypt_api_key(self._settings, row.api_key_enc),
                    chat_model=row.chat_model,
                    fallback_model=row.fallback_model or "",
                    supports_json_schema=row.supports_json_schema,
                    source="db",
                )
        except Exception:
            logger.exception("provider_db_load_failed_falling_back_to_env")
        return env_provider(self._settings)

    def start_listener(self) -> None:
        """worker 侧：订阅失效广播，收到即清缓存（热切换的即时性来源）。"""
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen())

    async def stop_listener(self) -> None:
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None

    async def _listen(self) -> None:
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(PROVIDER_INVALIDATE_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        logger.info("provider_config_invalidated_by_broadcast")
                        self.invalidate()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("provider_listener_reconnecting")
                await asyncio.sleep(5)


async def publish_invalidation(redis: Redis) -> None:
    """api 侧：供应商增改/激活后广播，让所有 worker 立即清缓存。"""
    try:
        await redis.publish(PROVIDER_INVALIDATE_CHANNEL, "changed")
    except Exception:
        logger.warning("provider_invalidation_publish_failed")  # 60s TTL 仍会兜底


class DynamicChatClient:
    """每次调用解析当前供应商配置；配置变化时重建底层 OpenAIChatClient（§12 热切换）。"""

    def __init__(self, source: ProviderSource) -> None:
        self._source = source
        self._active_config: ProviderConfig | None = None
        self._client: object | None = None

    async def chat(self, messages, *, purpose, timeout_s, schema=None):  # type: ignore[no-untyped-def]
        from llm.client import OpenAIChatClient

        config = await self._source.get()
        if config is None:
            raise ProviderNotConfigured("无可用 LLM 供应商（DB 未激活且 env 未配置）")
        if config != self._active_config:
            self._client = OpenAIChatClient(
                base_url=config.base_url,
                api_key=config.api_key,
                model=config.chat_model,
                fallback_model=config.fallback_model,
                supports_json_schema=config.supports_json_schema,
            )
            self._active_config = config
            logger.info("chat_client_rebuilt", source=config.source, model=config.chat_model)
        assert self._client is not None
        return await self._client.chat(  # type: ignore[attr-defined]
            messages, purpose=purpose, timeout_s=timeout_s, schema=schema
        )
