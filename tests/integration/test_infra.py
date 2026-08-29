"""M1 集成冒烟：migration 已应用的数据库与 Redis 可达（CI services / 本地 compose）。"""

from sqlalchemy import text

from tests.conftest import REDIS_URL


async def test_migrated_schema_reachable(session_factory) -> None:
    async with session_factory() as session:
        for table in ("telegram_updates", "conversations", "messages", "leads"):
            result = await session.execute(text(f"SELECT count(*) FROM {table}"))
            assert result.scalar() == 0


async def test_redis_reachable(redis_client) -> None:
    assert REDIS_URL is not None
    assert await redis_client.ping()
