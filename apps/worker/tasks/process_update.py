"""消息处理任务：domain.orchestrator.run_process_update 的 arq 薄包装（技术方案 §6）。"""

from typing import Any

import structlog
from domain.orchestrator import run_process_update
from observability.logging import bind_trace_id

logger = structlog.get_logger()


async def process_update(ctx: dict[str, Any], update_id: int, trace_id: str | None = None) -> str:
    if trace_id:
        bind_trace_id(trace_id)
    outcome = await run_process_update(
        ctx["session_factory"],
        ctx["locker"],
        ctx["sender"],
        ctx.get("brain"),
        update_id,
        reply_deadline_s=ctx["settings"].reply_deadline_s,
    )
    if outcome == "locked":
        # 会话被占用：已回置 queued，延迟重入队（§6 第 1 步）；job_id 留空避免与在跑任务冲突
        await ctx["redis"].enqueue_job("process_update", update_id, trace_id, _defer_by=2)
    elif outcome == "replied":
        # §6 第 5 步：回复已送达，线索提取交给独立任务
        await ctx["redis"].enqueue_job("extract_lead", update_id, trace_id)
    logger.info("process_update_finished", update_id=update_id, outcome=outcome)
    return outcome
