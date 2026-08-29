"""索引流程（技术方案 §6 RAG 细节）：解析 → 切分 → embedding → 版本化原子切换。

顺序保证无"知识真空期"：新 chunks 以 version+1 写入（唯一约束 + ON CONFLICT 幂等）
→ 单条 UPDATE 翻转 documents.version 并置 active → 删除旧版本 chunks。
"""

from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol

import structlog
from domain import repositories
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from llm import chunking
from llm.client import Embedder

logger = structlog.get_logger()

IndexOutcome = Literal["indexed", "locked", "missing", "failed"]


class Locker(Protocol):
    def hold(self, entity_id: int) -> AbstractAsyncContextManager[bool]: ...


async def run_index_document(
    session_factory: async_sessionmaker[AsyncSession],
    locker: Locker,
    embedder: Embedder | None,
    document_id: int,
) -> IndexOutcome:
    async with locker.hold(document_id) as acquired:
        if not acquired:
            logger.info("index_locked", document_id=document_id)
            return "locked"

        async with session_factory() as session:
            doc = await repositories.get_document(session, document_id)
            if doc is None:
                return "missing"
            await repositories.set_document_status(session, document_id, "indexing")
            await session.commit()

        try:
            if embedder is None:
                raise RuntimeError("未配置 embedding（缺少 LLM_API_KEY），拒绝用假向量污染知识库")
            text = chunking.load_source_text(doc.source_type, doc.storage_path, doc.source_url)
            chunks = chunking.split_text(text, doc.source_type)
            if not chunks:
                raise ValueError("文档没有可索引内容")
            vectors = await embedder.embed([c.content for c in chunks])

            new_version = doc.version + 1
            async with session_factory() as session:
                await repositories.insert_chunks(
                    session,
                    document_id,
                    new_version,
                    [
                        (c.chunk_index, c.content, c.metadata, v)
                        for c, v in zip(chunks, vectors, strict=True)
                    ],
                )
                await session.commit()
                await repositories.activate_document_version(session, document_id, new_version)
                await session.commit()
                await repositories.delete_chunks_except(session, document_id, new_version)
                await session.commit()
            logger.info(
                "document_indexed",
                document_id=document_id,
                version=new_version,
                chunks=len(chunks),
            )
            return "indexed"
        except Exception as exc:
            logger.exception("index_failed", document_id=document_id)
            async with session_factory() as session:
                await repositories.set_document_status(session, document_id, "failed")
                await session.commit()
            logger.warning("document_index_failed", document_id=document_id, error=repr(exc))
            return "failed"
