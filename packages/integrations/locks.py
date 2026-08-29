"""Redis 会话锁（技术方案 §6 第 1 步）：TTL 60s、随机 token、任务内续期、Lua 安全释放。"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any, cast

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger()

# 只释放/续期自己持有的锁：token 不匹配说明锁已过期并被他人持有
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class RedisLock:
    """按前缀隔离的通用锁：会话锁 conv:{chat_id}、索引锁 index:{document_id}。"""

    def __init__(
        self,
        redis: Redis,
        prefix: str = "conv",
        ttl_seconds: int = 60,
        renew_every_seconds: int = 20,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._renew_every = renew_every_seconds

    @asynccontextmanager
    async def hold(self, entity_id: int) -> AsyncIterator[bool]:
        key = f"{self._prefix}:{entity_id}"
        token = uuid.uuid4().hex
        acquired = await self._redis.set(key, token, nx=True, ex=self._ttl)
        if not acquired:
            yield False
            return

        renew_task = asyncio.create_task(self._renew_loop(key, token))
        try:
            yield True
        finally:
            renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew_task
            try:
                await self._eval(_RELEASE_LUA, key, token)
            except Exception:
                logger.warning("lock_release_failed", key=key)

    async def _renew_loop(self, key: str, token: str) -> None:
        while True:
            await asyncio.sleep(self._renew_every)
            try:
                renewed = await self._eval(_RENEW_LUA, key, token, str(self._ttl))
                if not renewed:
                    logger.warning("lock_renew_lost", key=key)
                    return
            except Exception:
                logger.warning("lock_renew_failed", key=key)

    def _eval(self, script: str, key: str, *args: str) -> Awaitable[Any]:
        # redis-py 的 eval 类型标注为 sync/async 联合，这里收窄为 async
        return cast(Awaitable[Any], self._redis.eval(script, 1, key, *args))
