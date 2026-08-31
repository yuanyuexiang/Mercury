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
from domain.models import EMBEDDING_DIM, LlmProvider
from domain.schemas import LlmNotConfiguredError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()

PROVIDER_INVALIDATE_CHANNEL = "mercury:llm_provider_changed"
CACHE_TTL_S = 60.0


# 领域层异常的别名：编排层据此降级为"系统未就绪"文案
ProviderNotConfigured = LlmNotConfiguredError


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    chat_model: str
    fallback_model: str = ""
    supports_json_schema: bool = True
    embed_model: str = ""  # 空 = 该供应商不提供 embedding，用 env 兜底
    source: str = "env"  # env|db，日志与后台展示用


@dataclass(frozen=True)
class EmbedConfig:
    """embedding 独立解析结果：对话与知识库检索可以来自不同供应商（§12 修订）。"""

    base_url: str
    api_key: str
    embed_model: str
    source: str = "env"  # env|db


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
            embed_model=settings.llm_embed_model,
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
        self._embed_cache: EmbedConfig | None = None
        self._embed_cached_at = 0.0
        self._listener_task: asyncio.Task[None] | None = None

    async def get(self) -> ProviderConfig | None:
        if self._cache is not None and (time.monotonic() - self._cached_at) < CACHE_TTL_S:
            return self._cache
        config = await self._load()
        self._cache = config
        self._cached_at = time.monotonic()
        return config

    async def get_embed(self) -> EmbedConfig | None:
        """embedding 配置独立解析：激活供应商优先，其次任一配了检索模型的供应商，最后 env。

        对话与检索因此可以不同家（如智谱管对话 + 硅基流动管检索）——检索模型
        配在任意一行供应商上即可，无需激活（激活只决定谁来对话）。
        """
        if (
            self._embed_cache is not None
            and (time.monotonic() - self._embed_cached_at) < CACHE_TTL_S
        ):
            return self._embed_cache
        config = await self._load_embed()
        self._embed_cache = config
        self._embed_cached_at = time.monotonic()
        return config

    def invalidate(self) -> None:
        self._cache = None
        self._cached_at = 0.0
        self._embed_cache = None
        self._embed_cached_at = 0.0

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
                    embed_model=row.embed_model or "",
                    source="db",
                )
        except Exception:
            logger.exception("provider_db_load_failed_falling_back_to_env")
        return env_provider(self._settings)

    async def _load_embed(self) -> EmbedConfig | None:
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(LlmProvider)
                        .where(LlmProvider.embed_model.is_not(None))
                        .order_by(LlmProvider.is_active.desc(), LlmProvider.updated_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if row is not None and row.embed_model:
                return EmbedConfig(
                    base_url=row.base_url,
                    api_key=decrypt_api_key(self._settings, row.api_key_enc),
                    embed_model=row.embed_model,
                    source="db",
                )
        except Exception:
            logger.exception("embed_db_load_failed_falling_back_to_env")
        if self._settings.llm_api_key:
            return EmbedConfig(
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key,
                embed_model=self._settings.llm_embed_model,
                source="env",
            )
        return None

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
        if not config.chat_model:
            # 仅做知识库检索的供应商（chat_model 为空）被误激活时明确降级
            raise ProviderNotConfigured("激活的供应商未配置对话模型")
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


class DynamicEmbedder:
    """每次调用解析供应商配置的 embedder（§12 修订：后台可配 embedding）。

    解析顺序见 ProviderSource.get_embed（激活供应商 → 任一配了检索模型的供应商 → env）。
    请求携带 dimensions=EMBEDDING_DIM（Matryoshka 模型按需输出，不支持的上游自动降级）。
    维度守卫：返回向量必须是 EMBEDDING_DIM（1536）维，否则报明确错误——
    换维度意味着全量重建向量库，不允许静默发生。
    """

    def __init__(self, source: ProviderSource, settings: Settings) -> None:
        self._source = source
        self._settings = settings
        self._active_key: tuple[str, str, str] | None = None
        self._embedder: object | None = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from llm.client import OpenAIEmbedder

        config = await self._source.get_embed()
        if config is None:
            raise LlmNotConfiguredError(
                "无可用 embedding 配置（没有供应商配置「知识库检索模型」，env 也无 LLM_API_KEY）"
            )
        key = (config.base_url, config.api_key, config.embed_model)
        if key != self._active_key:
            self._embedder = OpenAIEmbedder(*key, dimensions=EMBEDDING_DIM)
            self._active_key = key
            logger.info("embedder_rebuilt", model=key[2], source=config.source)
        assert self._embedder is not None
        vectors = await self._embedder.embed(texts)  # type: ignore[attr-defined]
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise RuntimeError(
                f"embedding 维度 {len(vectors[0])} ≠ {EMBEDDING_DIM}：换维度需全量重建向量库，"
                f"请改用 {EMBEDDING_DIM} 维模型（如 text-embedding-3-small）"
            )
        return vectors
