"""§6 RAG 细节：索引闭环、版本化原子切换、检索过滤、重试幂等。"""

from pathlib import Path
from typing import Any

from domain import repositories
from domain.models import KnowledgeChunk, KnowledgeDocument
from llm.chunking import checksum_of
from llm.client import DeterministicFakeEmbedder
from llm.indexing import run_index_document
from llm.rag import retrieve
from sqlalchemy import func, select

DOC_TEXT = """# 测试产品

## 部署

本产品支持私有化部署，提供 Docker 与 Kubernetes 交付。

## 定价

团队版每席位每月 29 美元，50 人团队年费约 17400 美元。
"""


async def _create_doc(session_factory, tmp_path: Path, name: str = "doc.md") -> int:
    path = tmp_path / name
    path.write_text(DOC_TEXT, encoding="utf-8")
    async with session_factory() as session:
        doc = await repositories.create_document(
            session,
            title="测试产品资料",
            source_type="markdown",
            storage_path=str(path),
            checksum=checksum_of(DOC_TEXT),
        )
        await session.commit()
        return doc.id


async def test_index_and_retrieve_roundtrip(session_factory, index_locker, tmp_path) -> None:
    embedder = DeterministicFakeEmbedder()
    doc_id = await _create_doc(session_factory, tmp_path)

    assert await run_index_document(session_factory, index_locker, embedder, doc_id) == "indexed"

    async with session_factory() as session:
        doc = (await session.execute(select(KnowledgeDocument))).scalar_one()
        assert doc.status == "active" and doc.version == 2
        chunks = (await session.execute(select(KnowledgeChunk))).scalars().all()
        assert chunks and all(c.version == 2 for c in chunks)
        target = next(c for c in chunks if "私有化部署" in c.content)

        # 假向量同文本相似度=1：用 chunk 原文当查询必命中该 chunk
        results = await retrieve(session, embedder, target.content, top_k=6, min_similarity=0.60)
        assert results and results[0].chunk_id == target.id
        assert results[0].similarity > 0.99
        assert results[0].document_title == "测试产品资料"

        # 无关查询：随机单位向量近似正交 → 全部被阈值过滤（无答案路径）
        assert await retrieve(session, embedder, "完全无关的问题 xyz", 6, 0.60) == []


async def test_reindex_atomic_version_switch(session_factory, index_locker, tmp_path) -> None:
    embedder = DeterministicFakeEmbedder()
    doc_id = await _create_doc(session_factory, tmp_path)
    await run_index_document(session_factory, index_locker, embedder, doc_id)
    assert await run_index_document(session_factory, index_locker, embedder, doc_id) == "indexed"

    async with session_factory() as session:
        doc = (await session.execute(select(KnowledgeDocument))).scalar_one()
        assert doc.version == 3
        versions = (
            (await session.execute(select(KnowledgeChunk.version).distinct())).scalars().all()
        )
        assert versions == [3], "旧版本 chunks 应在翻转后删除"


async def test_insert_chunks_retry_idempotent(session_factory, tmp_path) -> None:
    doc_id = await _create_doc(session_factory, tmp_path)
    embedder = DeterministicFakeEmbedder()
    [vec] = await embedder.embed(["内容"])
    rows: list[tuple[int, str, dict[str, Any], list[float]]] = [(0, "内容", {}, vec)]
    async with session_factory() as session:
        await repositories.insert_chunks(session, doc_id, 2, rows)
        await repositories.insert_chunks(session, doc_id, 2, rows)  # 重试
        await session.commit()
        count = (await session.execute(select(func.count()).select_from(KnowledgeChunk))).scalar()
    assert count == 1


async def test_disabled_document_excluded(session_factory, index_locker, tmp_path) -> None:
    embedder = DeterministicFakeEmbedder()
    doc_id = await _create_doc(session_factory, tmp_path)
    await run_index_document(session_factory, index_locker, embedder, doc_id)

    async with session_factory() as session:
        chunk = (await session.execute(select(KnowledgeChunk))).scalars().first()
        assert chunk is not None
        query = chunk.content
        assert await retrieve(session, embedder, query, 6, 0.60)

        await repositories.set_document_status(session, doc_id, "disabled")
        await session.commit()
        assert await retrieve(session, embedder, query, 6, 0.60) == []


async def test_index_failure_marks_failed_and_keeps_old_version(
    session_factory, index_locker, tmp_path
) -> None:
    embedder = DeterministicFakeEmbedder()
    doc_id = await _create_doc(session_factory, tmp_path)
    await run_index_document(session_factory, index_locker, embedder, doc_id)

    # 源文件被删导致重索引失败：状态 failed，但旧版本 chunks 原样保留（无知识真空）
    async with session_factory() as session:
        doc = await repositories.get_document(session, doc_id)
        assert doc is not None
        Path(doc.storage_path).unlink()  # type: ignore[arg-type]  # noqa: ASYNC240

    assert await run_index_document(session_factory, index_locker, embedder, doc_id) == "failed"
    async with session_factory() as session:
        doc = (await session.execute(select(KnowledgeDocument))).scalar_one()
        assert doc.status == "failed" and doc.version == 2
        count = (await session.execute(select(func.count()).select_from(KnowledgeChunk))).scalar()
        assert count and count > 0
