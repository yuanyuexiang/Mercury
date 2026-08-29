"""线索提取任务：domain.orchestrator.run_extract_lead 的 arq 薄包装（技术方案 §6）。"""

from typing import Any

import structlog
from domain.orchestrator import run_extract_lead
from observability.logging import bind_trace_id

logger = structlog.get_logger()


async def extract_lead(ctx: dict[str, Any], update_id: int, trace_id: str | None = None) -> str:
    if trace_id:
        bind_trace_id(trace_id)
    outcome = await run_extract_lead(
        ctx["session_factory"], ctx["locker"], ctx["sender"], ctx.get("extractor"), update_id
    )
    if outcome == "locked":
        # 会话被占用：状态仍是 replied，延迟重入队（扫描器③也会兜底）
        await ctx["redis"].enqueue_job("extract_lead", update_id, trace_id, _defer_by=2)
    logger.info("extract_lead_finished", update_id=update_id, outcome=outcome)
    return outcome
