"""CRM 同步任务：domain.orchestrator.run_sync_lead 的 arq 薄包装（技术方案 §11）。"""

from typing import Any

import structlog
from domain.orchestrator import run_sync_lead
from observability.logging import bind_trace_id

logger = structlog.get_logger()


async def sync_lead(ctx: dict[str, Any], job_id: int, trace_id: str | None = None) -> str:
    if trace_id:
        bind_trace_id(trace_id)
    outcome, retry_delay = await run_sync_lead(
        ctx["session_factory"],
        ctx.get("sync_port"),
        ctx.get("summarizer"),
        ctx["sender"],
        job_id,
    )
    if outcome == "retry" and retry_delay is not None:
        # 退避重试（§11）：2^attempts 分钟；enqueue 丢失由扫描器④'兜底
        await ctx["redis"].enqueue_job("sync_lead", job_id, trace_id, _defer_by=retry_delay)
    logger.info("sync_lead_finished", job_id=job_id, outcome=outcome)
    return outcome
