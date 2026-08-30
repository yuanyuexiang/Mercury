"""系统设置存取（migration 0007）：后台可配 Telegram 对接与品牌文案。

延续 §12 供应商配置的模式：DB 优先、env 兜底；进程内缓存 60s；
api 改配置后发 Redis 广播，worker 订阅即清缓存——改完立即生效，不重启。
敏感值（bot token）Fernet 密文入库，主密钥 SETTINGS_ENCRYPTION_KEY 仅在 env。
"""

import asyncio
import contextlib
import time

import structlog
from cryptography.fernet import Fernet
from domain.config import Settings
from domain.models import AppSetting
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()

SETTINGS_INVALIDATE_CHANNEL = "mercury:app_settings_changed"
CACHE_TTL_S = 60.0

# 已知配置键（后台「系统设置」页的全集；DB 值为空串 = 未设置，回落 env）
KEY_TELEGRAM_BOT_TOKEN = "telegram_bot_token"  # 加密存储
KEY_OPERATOR_CHAT_ID = "operator_telegram_chat_id"
KEY_BRAND_NAME = "brand_name"
KEY_BOT_TONE_HINT = "bot_tone_hint"

ENCRYPTED_KEYS = frozenset({KEY_TELEGRAM_BOT_TOKEN})


def _fernet(settings: Settings) -> Fernet:
    if not settings.settings_encryption_key:
        raise RuntimeError("缺少 SETTINGS_ENCRYPTION_KEY（Fernet 主密钥）")
    return Fernet(settings.settings_encryption_key.encode())


def encrypt_value(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt_value(settings: Settings, ciphertext: str) -> str:
    return _fernet(settings).decrypt(ciphertext.encode()).decode()


class AppSettingsStore:
    """DB 优先、env 兜底的系统设置源；60s TTL + Redis 广播失效。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._settings = settings
        self._cache: dict[str, str] | None = None
        self._cached_at = 0.0
        self._listener_task: asyncio.Task[None] | None = None

    async def _db_values(self) -> dict[str, str]:
        if self._cache is not None and (time.monotonic() - self._cached_at) < CACHE_TTL_S:
            return self._cache
        values: dict[str, str] = {}
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(select(AppSetting))).scalars().all()
            for row in rows:
                if row.is_encrypted:
                    try:
                        values[row.key] = decrypt_value(self._settings, row.value)
                    except Exception:
                        logger.exception("app_setting_decrypt_failed", key=row.key)
                else:
                    values[row.key] = row.value
        except Exception:
            logger.exception("app_settings_db_load_failed_falling_back_to_env")
        self._cache = values
        self._cached_at = time.monotonic()
        return values

    async def get(self, key: str, env_fallback: str = "") -> str:
        """DB 非空值优先；空串或缺失回落 env。"""
        values = await self._db_values()
        db_value = values.get(key, "")
        return db_value if db_value else env_fallback

    async def source_of(self, key: str, env_fallback: str = "") -> str:
        """该键当前生效值来源：db | env | none（后台展示用）。"""
        values = await self._db_values()
        if values.get(key, ""):
            return "db"
        return "env" if env_fallback else "none"

    # ---- 业务语义 helpers ----

    async def telegram_bot_token(self) -> str:
        return await self.get(KEY_TELEGRAM_BOT_TOKEN, self._settings.telegram_bot_token)

    async def operator_chat_id(self) -> str:
        return await self.get(KEY_OPERATOR_CHAT_ID, self._settings.operator_telegram_chat_id)

    async def brand_name(self) -> str:
        return await self.get(KEY_BRAND_NAME, self._settings.brand_name)

    async def bot_tone_hint(self) -> str:
        return await self.get(KEY_BOT_TONE_HINT, self._settings.bot_tone_hint)

    # ---- 写入（api 侧） ----

    async def set_values(self, values: dict[str, str]) -> None:
        """upsert 多个设置项并立即清本地缓存；调用方随后应 publish_invalidation。"""
        async with self._session_factory() as session:
            for key, value in values.items():
                encrypted = key in ENCRYPTED_KEYS and bool(value)
                stored = encrypt_value(self._settings, value) if encrypted else value
                stmt = (
                    pg_insert(AppSetting)
                    .values(key=key, value=stored, is_encrypted=encrypted)
                    .on_conflict_do_update(
                        index_elements=["key"],
                        set_={
                            "value": stored,
                            "is_encrypted": encrypted,
                            "updated_at": func.now(),
                        },
                    )
                )
                await session.execute(stmt)
            await session.commit()
        self.invalidate()

    def invalidate(self) -> None:
        self._cache = None
        self._cached_at = 0.0

    # ---- 广播失效（与 ProviderSource 相同机制） ----

    def start_listener(self) -> None:
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
                await pubsub.subscribe(SETTINGS_INVALIDATE_CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        logger.info("app_settings_invalidated_by_broadcast")
                        self.invalidate()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("app_settings_listener_reconnecting")
                await asyncio.sleep(5)


async def publish_invalidation(redis: Redis) -> None:
    try:
        await redis.publish(SETTINGS_INVALIDATE_CHANNEL, "changed")
    except Exception:
        logger.warning("app_settings_invalidation_publish_failed")  # 60s TTL 仍会兜底
