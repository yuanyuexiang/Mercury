"""沉睡线索唤醒任务：domain.orchestrator.run_revive_leads 的 cron 薄包装。

每日 UTC 02:30（北京 10:30，工作时间开始，不深夜打扰）；REVIVE_ENABLED=false 可关。
"""

from typing import Any

import structlog
from domain.orchestrator import run_revive_leads

logger = structlog.get_logger()


async def revive_sleeping_leads(ctx: dict[str, Any]) -> int:
    store = ctx["app_settings"]  # 后台「系统设置」可配，env 仅兜底
    if not await store.revive_enabled():
        return 0
    sent = await run_revive_leads(
        ctx["session_factory"],
        ctx["sender"],
        after_days=await store.revive_after_days(),
        max_attempts=await store.revive_max_attempts(),
        brand_name=await store.brand_name(),
    )
    logger.info("revive_sweep_finished", sent=sent)
    return sent
