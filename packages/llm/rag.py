"""检索与受约束生成（技术方案 §6 RAG 细节）。

只检索 status='active' 且 chunks.version = documents.version 的内容——
重索引期间旧版本一直可用，不存在"知识真空期"。
生成约束见 prompts.RAG_SYSTEM（§9.2）：资料未覆盖输出 NO_ANSWER_MARKER → 拒答路径。
"""

from dataclasses import dataclass
from typing import Any

from domain.models import KnowledgeChunk, KnowledgeDocument
from domain.schemas import Deadline, RagAnswer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm.client import ChatClient, Embedder
from llm.prompts import NO_ANSWER_MARKER, RAG_SYSTEM


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_title: str
    content: str
    similarity: float
    metadata: dict[str, Any]


async def retrieve(
    session: AsyncSession,
    embedder: Embedder,
    query: str,
    top_k: int = 6,
    min_similarity: float = 0.60,
) -> list[RetrievedChunk]:
    """cosine top-k + 相似度阈值过滤；过滤后为空即"无答案路径"（§6 第 3d 步）。"""
    [query_vector] = await embedder.embed([query])
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument.title, distance.label("distance"))
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.status == "active",
            KnowledgeChunk.version == KnowledgeDocument.version,
        )
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()
    results: list[RetrievedChunk] = []
    for chunk, title, dist in rows:
        similarity = 1.0 - float(dist)
        if similarity < min_similarity:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                content=chunk.content,
                similarity=similarity,
                metadata=chunk.meta,
            )
        )
    return results


async def generate_answer(
    session: AsyncSession,
    embedder: Embedder,
    chat: "ChatClient",
    question: str,
    history: list[dict[str, str]],
    language: str,
    deadline: "Deadline",
    top_k: int = 6,
    min_similarity: float = 0.60,
) -> "RagAnswer":
    """检索 + 受约束生成（§6 第 3d 步）。检索为空 / 预算耗尽 / 模型说无法确认 → refused。"""
    chunks = await retrieve(session, embedder, question, top_k, min_similarity)
    if not chunks:
        return RagAnswer(refused=True)

    timeout = deadline.remaining()
    if timeout <= 0.2:
        return RagAnswer(refused=True, source_chunk_ids=[c.chunk_id for c in chunks])

    materials = "\n\n".join(
        f"[{i + 1}] ({c.document_title}) {c.content}" for i, c in enumerate(chunks)
    )
    system = RAG_SYSTEM.format(
        no_answer_marker=NO_ANSWER_MARKER, language=language, materials=materials
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *history[-4:],
        {"role": "user", "content": question},
    ]
    result = await chat.chat(messages, purpose="rag", timeout_s=timeout)
    text = (result.content or "").strip()
    if not text or NO_ANSWER_MARKER in text:
        return RagAnswer(
            refused=True,
            source_chunk_ids=[c.chunk_id for c in chunks],
            model_name=result.model_name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
        )
    return RagAnswer(
        refused=False,
        text=text,
        source_chunk_ids=[c.chunk_id for c in chunks],
        model_name=result.model_name,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=result.latency_ms,
    )
