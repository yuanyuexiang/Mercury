"""兜底扫描器（arq cron，每 60s；技术方案 §6）：先原子重置、再入队，只入队 RETURNING 的 ID。"""

from typing import Any

import structlog
from domain import repositories

logger = structlog.get_logger()


async def sweep(ctx: dict[str, Any]) -> dict[str, int]:
    session_factory = ctx["session_factory"]
    async with session_factory() as session:
        # ① processing 租约过期 → 原子重置为 queued（与管线第 0 步抢占条件闭环）
        reset_ids = await repositories.reset_expired_processing(session, lease_minutes=5)
        await session.commit()
        # ② queued 超 60s 未被消费（覆盖"落库成功但入队失败"的窗口）
        stale_ids = await repositories.stale_queued_ids(session, stale_seconds=60)

    for update_id in set(reset_ids) | set(stale_ids):
        await ctx["redis"].enqueue_job("process_update", update_id, None)

    # ③ replied 超 5min（extract_lead 任务丢失）→ 补 enqueue；
    #    extracting 租约过期（worker 崩溃）→ 原子重置回 replied 再入队（§6）
    async with session_factory() as session:
        extracting_ids = await repositories.reset_expired_extracting(session, lease_minutes=5)
        await session.commit()
        replied_ids = await repositories.stale_replied_ids(session, stale_seconds=300)
    for update_id in set(replied_ids) | set(extracting_ids):
        await ctx["redis"].enqueue_job("extract_lead", update_id, None)

    # ④ integration_jobs：running 超 10min 先原子重置为 pending 再入队；
    #    pending 入队丢失（新建未消费 / 退避到期未重入队）→ 补 enqueue（§11）
    async with session_factory() as session:
        job_reset_ids = await repositories.reset_expired_running_jobs(session, lease_minutes=10)
        await session.commit()
        job_stale_ids = await repositories.stale_pending_job_ids(session, grace_seconds=300)
    for job_id in set(job_reset_ids) | set(job_stale_ids):
        await ctx["redis"].enqueue_job("sync_lead", job_id, None)

    recovered = reset_ids or stale_ids or replied_ids or job_reset_ids or job_stale_ids
    if recovered:
        logger.info(
            "sweeper_recovered",
            reset=reset_ids,
            stale=stale_ids,
            replied=replied_ids,
            job_reset=job_reset_ids,
            job_stale=job_stale_ids,
        )
    return {
        "reset": len(reset_ids),
        "stale": len(stale_ids),
        "replied": len(replied_ids),
        "jobs": len(set(job_reset_ids) | set(job_stale_ids)),
    }


async def retention_cleanup(ctx: dict[str, Any]) -> dict[str, int]:
    """每日数据保留期清理（§14，DATA_RETENTION_DAYS）。"""
    settings = ctx["settings"]
    async with ctx["session_factory"]() as session:
        removed = await repositories.cleanup_expired_data(session, settings.data_retention_days)
        await session.commit()
    if any(removed.values()):
        logger.info("retention_cleanup_done", **removed)
    return removed
