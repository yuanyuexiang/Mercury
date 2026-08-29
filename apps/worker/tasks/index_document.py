"""文档索引任务：llm.indexing.run_index_document 的 arq 薄包装（技术方案 §6 RAG 细节）。"""

from typing import Any

import structlog
from llm.indexing import run_index_document
from observability.logging import bind_trace_id

logger = structlog.get_logger()


async def index_document(ctx: dict[str, Any], document_id: int, trace_id: str | None = None) -> str:
    if trace_id:
        bind_trace_id(trace_id)
    outcome = await run_index_document(
        ctx["session_factory"], ctx["index_locker"], ctx.get("embedder"), document_id
    )
    logger.info("index_document_finished", document_id=document_id, outcome=outcome)
    return outcome
