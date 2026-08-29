"""数据访问封装（domain 不依赖框架，技术方案 §3 原则）。

所有幂等语义在这里落地：update 原子抢占、inbound 唯一、outbound delivery_key、
租约过期重置（§5/§6）。
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domain.models import (
    Conversation,
    KnowledgeChunk,
    KnowledgeDocument,
    Message,
    TelegramUpdate,
    User,
)

# ---------- telegram_updates ----------


async def insert_update(session: AsyncSession, update_id: int, payload: dict[str, Any]) -> bool:
    """幂等落库：已存在（重复推送）返回 False。"""
    stmt = (
        pg_insert(TelegramUpdate)
        .values(update_id=update_id, payload=payload)
        .on_conflict_do_nothing(index_elements=["update_id"])
    )
    result = await session.execute(stmt)
    return bool(cast(CursorResult[Any], result).rowcount)


async def claim_update(session: AsyncSession, update_id: int) -> dict[str, Any] | None:
    """原子抢占（§6 第 0 步）：仅 queued/failed 可被抢；抢不到返回 None。"""
    stmt = (
        update(TelegramUpdate)
        .where(
            TelegramUpdate.update_id == update_id,
            TelegramUpdate.status.in_(["queued", "failed"]),
        )
        .values(status="processing", picked_at=func.now())
        .returning(TelegramUpdate.payload)
    )
    result = await session.execute(stmt)
    row = result.first()
    return row[0] if row else None


async def requeue_update(session: AsyncSession, update_id: int) -> None:
    """锁竞争让位：状态回置 queued，等待重新入队（§6 第 1 步）。"""
    await session.execute(
        update(TelegramUpdate)
        .where(TelegramUpdate.update_id == update_id)
        .values(status="queued", picked_at=None)
    )


async def mark_update(
    session: AsyncSession, update_id: int, status: str, error: str | None = None
) -> None:
    values: dict[str, Any] = {"status": status, "error": error}
    if status in ("done", "skipped", "failed"):
        values["processed_at"] = func.now()
    await session.execute(
        update(TelegramUpdate).where(TelegramUpdate.update_id == update_id).values(**values)
    )


async def reset_expired_processing(session: AsyncSession, lease_minutes: int = 5) -> list[int]:
    """兜底扫描器①：租约过期的 processing 原子重置为 queued，返回待重新入队的 ID（§6）。"""
    deadline = datetime.now(UTC) - timedelta(minutes=lease_minutes)
    stmt = (
        update(TelegramUpdate)
        .where(TelegramUpdate.status == "processing", TelegramUpdate.picked_at < deadline)
        .values(status="queued", picked_at=None)
        .returning(TelegramUpdate.update_id)
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.fetchall()]


async def stale_queued_ids(session: AsyncSession, stale_seconds: int = 60) -> list[int]:
    """兜底扫描器②：落库超时未被消费的 queued（覆盖入队失败窗口），直接补 enqueue（§6）。"""
    deadline = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    stmt = select(TelegramUpdate.update_id).where(
        TelegramUpdate.status == "queued", TelegramUpdate.received_at < deadline
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.fetchall()]


# ---------- users / conversations ----------


async def upsert_user(session: AsyncSession, tg_user: dict[str, Any]) -> User:
    stmt = (
        pg_insert(User)
        .values(
            telegram_user_id=tg_user["id"],
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            last_name=tg_user.get("last_name"),
            language_code=tg_user.get("language_code"),
        )
        .on_conflict_do_update(
            index_elements=["telegram_user_id"],
            set_={
                "username": tg_user.get("username"),
                "first_name": tg_user.get("first_name"),
                "last_name": tg_user.get("last_name"),
                "language_code": tg_user.get("language_code"),
                "updated_at": func.now(),
            },
        )
        .returning(User)
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_open_conversation(
    session: AsyncSession, telegram_chat_id: int, user_id: int
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.telegram_chat_id == telegram_chat_id,
        Conversation.user_id == user_id,
        Conversation.status != "closed",
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_create_open_conversation(
    session: AsyncSession, telegram_chat_id: int, user_id: int
) -> Conversation:
    conv = await get_open_conversation(session, telegram_chat_id, user_id)
    if conv is not None:
        return conv
    stmt = (
        pg_insert(Conversation)
        .values(telegram_chat_id=telegram_chat_id, user_id=user_id)
        .on_conflict_do_nothing(
            index_elements=["telegram_chat_id", "user_id"],
            index_where=text("status != 'closed'"),
        )
        .returning(Conversation)
    )
    conv = (await session.execute(stmt)).scalar_one_or_none()
    if conv is not None:
        return conv
    # 并发下被别人先建：会话锁使同 chat 串行，这里只是兜底
    conv = await get_open_conversation(session, telegram_chat_id, user_id)
    assert conv is not None
    return conv


async def close_conversation(session: AsyncSession, conversation_id: int) -> None:
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(status="closed", closed_at=func.now())
    )


async def touch_last_message(session: AsyncSession, conversation_id: int) -> None:
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(last_message_at=func.now())
    )


# ---------- messages ----------


async def save_inbound_message(
    session: AsyncSession,
    conversation_id: int,
    update_id: int,
    telegram_message_id: int,
    content: str,
    content_type: str = "text",
) -> None:
    """幂等保存 inbound（部分唯一索引 + ON CONFLICT DO NOTHING，§6 第 2 步）。"""
    stmt = (
        pg_insert(Message)
        .values(
            conversation_id=conversation_id,
            telegram_message_id=telegram_message_id,
            source_update_id=update_id,
            direction="inbound",
            sender_type="user",
            content=content,
            content_type=content_type,
        )
        .on_conflict_do_nothing(
            index_elements=["conversation_id", "telegram_message_id"],
            index_where=text("direction = 'inbound'"),
        )
    )
    await session.execute(stmt)
    await touch_last_message(session, conversation_id)


async def get_recent_messages(
    session: AsyncSession, conversation_id: int, limit: int = 12
) -> list[Message]:
    """近期消息，时间正序（供 LLM 上下文，§6 第 3 步）。"""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars())
    return list(reversed(rows))


async def create_outbound_sending(
    session: AsyncSession,
    conversation_id: int,
    update_id: int,
    delivery_key: str,
    content: str,
    sender_type: str = "ai",
    answer_status: str | None = None,
    model_name: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    latency_ms: int | None = None,
    source_chunk_ids: list[int] | None = None,
) -> tuple[str, int | None]:
    """两阶段投递第一阶段（§6 第 4 步）。

    返回 ("created", message_id)：新建 sending 记录，可以发送；
    ("sent", None)：该投递意图已成功发过，跳过；
    ("sending", message_id)：残留 sending——上次投递结果不明，标 uncertain 不重发；
    ("skip", None)：uncertain/failed 残留，交由人工处理，不自动重发。
    """
    stmt = (
        pg_insert(Message)
        .values(
            conversation_id=conversation_id,
            source_update_id=update_id,
            delivery_key=delivery_key,
            direction="outbound",
            sender_type=sender_type,
            content=content,
            delivery_status="sending",
            answer_status=answer_status,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            source_chunk_ids=source_chunk_ids,
        )
        .on_conflict_do_nothing(
            index_elements=["delivery_key"], index_where=text("delivery_key IS NOT NULL")
        )
        .returning(Message.id)
    )
    row = (await session.execute(stmt)).first()
    if row:
        return "created", row[0]
    existing = (
        await session.execute(select(Message).where(Message.delivery_key == delivery_key))
    ).scalar_one()
    if existing.delivery_status == "sent":
        return "sent", None
    if existing.delivery_status == "sending":
        return "sending", existing.id
    return "skip", None


async def mark_outbound(
    session: AsyncSession,
    message_id: int,
    delivery_status: str,
    telegram_message_id: int | None = None,
) -> None:
    values: dict[str, Any] = {"delivery_status": delivery_status}
    if telegram_message_id is not None:
        values["telegram_message_id"] = telegram_message_id
    await session.execute(update(Message).where(Message.id == message_id).values(**values))


# ---------- knowledge（§6 RAG 细节：版本化原子切换） ----------


async def create_document(
    session: AsyncSession,
    title: str,
    source_type: str,
    storage_path: str | None = None,
    source_url: str | None = None,
    checksum: str | None = None,
) -> KnowledgeDocument:
    doc = KnowledgeDocument(
        title=title,
        source_type=source_type,
        storage_path=storage_path,
        source_url=source_url,
        checksum=checksum,
    )
    session.add(doc)
    await session.flush()
    return doc


async def get_document(session: AsyncSession, document_id: int) -> KnowledgeDocument | None:
    return await session.get(KnowledgeDocument, document_id)


async def find_document_by_checksum(
    session: AsyncSession, checksum: str
) -> KnowledgeDocument | None:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.checksum == checksum)
    return (await session.execute(stmt)).scalars().first()


async def set_document_status(session: AsyncSession, document_id: int, status: str) -> None:
    await session.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .values(status=status, updated_at=func.now())
    )


async def insert_chunks(
    session: AsyncSession,
    document_id: int,
    version: int,
    rows: list[tuple[int, str, dict[str, Any], list[float]]],
) -> None:
    """写入新版本 chunks；UNIQUE(document_id, version, chunk_index) + ON CONFLICT 保证重试幂等。"""
    stmt = (
        pg_insert(KnowledgeChunk)
        .values(
            [
                {
                    "document_id": document_id,
                    "version": version,
                    "chunk_index": chunk_index,
                    "content": content,
                    # 注意：必须用映射属性名 meta——"metadata" 会命中 DeclarativeBase.metadata
                    "meta": metadata,
                    "embedding": embedding,
                }
                for chunk_index, content, metadata, embedding in rows
            ]
        )
        .on_conflict_do_nothing(index_elements=["document_id", "version", "chunk_index"])
    )
    await session.execute(stmt)


async def activate_document_version(
    session: AsyncSession, document_id: int, new_version: int
) -> None:
    """原子翻转：单条 UPDATE 切换版本并置 active——翻转前旧版本一直可检索（§6）。"""
    await session.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .values(version=new_version, status="active", updated_at=func.now())
    )


async def delete_chunks_except(session: AsyncSession, document_id: int, keep_version: int) -> None:
    from sqlalchemy import delete

    await session.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document_id,
            KnowledgeChunk.version != keep_version,
        )
    )
