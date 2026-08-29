"""§6 兜底扫描器：先原子重置再入队；重置后的 update 可被再次抢占（第二轮评审修复项）。"""

from datetime import UTC, datetime, timedelta

from domain import repositories
from domain.models import TelegramUpdate
from domain.orchestrator import run_process_update
from sqlalchemy import select, update

from tests.conftest import tg_update


async def test_expired_processing_reset_and_reclaimable(
    session_factory, locker, sender, brain
) -> None:
    payload = tg_update(201, "stuck")
    async with session_factory() as session:
        await repositories.insert_update(session, 201, payload)
        # 模拟 worker 崩溃：processing 且租约早已过期
        await session.execute(
            update(TelegramUpdate)
            .where(TelegramUpdate.update_id == 201)
            .values(
                status="processing",
                picked_at=datetime.now(UTC) - timedelta(minutes=30),
            )
        )
        await session.commit()

    async with session_factory() as session:
        reset_ids = await repositories.reset_expired_processing(session, lease_minutes=5)
        await session.commit()
    assert reset_ids == [201]

    async with session_factory() as session:
        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "queued" and row.picked_at is None

    # 重置后能被第 0 步原子抢占并完整处理
    assert await run_process_update(session_factory, locker, sender, brain, 201) == "done"
    assert len(sender.sent) == 1


async def test_fresh_processing_not_reset(session_factory) -> None:
    async with session_factory() as session:
        await repositories.insert_update(session, 202, tg_update(202, "working"))
        await session.execute(
            update(TelegramUpdate)
            .where(TelegramUpdate.update_id == 202)
            .values(status="processing", picked_at=datetime.now(UTC))
        )
        await session.commit()
    async with session_factory() as session:
        assert await repositories.reset_expired_processing(session, lease_minutes=5) == []


async def test_stale_queued_detected(session_factory) -> None:
    async with session_factory() as session:
        await repositories.insert_update(session, 203, tg_update(203, "lost"))
        await session.execute(
            update(TelegramUpdate)
            .where(TelegramUpdate.update_id == 203)
            .values(received_at=datetime.now(UTC) - timedelta(minutes=10))
        )
        await session.commit()
    async with session_factory() as session:
        assert await repositories.stale_queued_ids(session, stale_seconds=60) == [203]
