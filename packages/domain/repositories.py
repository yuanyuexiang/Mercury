"""数据访问封装（domain 不依赖框架，技术方案 §3 原则）。

所有幂等语义在这里落地：update 原子抢占、inbound 唯一、outbound delivery_key、
租约过期重置（§5/§6）。
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import BigInteger, CursorResult, func, select, text, update
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domain.models import (
    AuditLog,
    Conversation,
    Handoff,
    IntegrationJob,
    KnowledgeChunk,
    KnowledgeDocument,
    Lead,
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
            index_elements=["tenant_id", "telegram_user_id"],
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
            index_elements=["tenant_id", "telegram_chat_id", "user_id"],
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


# ---------- leads / audit（§7/§8，M5） ----------

LEAD_SNAPSHOT_FIELDS = (
    "name",
    "company",
    "country",
    "business_email",
    "requirement",
    "team_size",
    "budget_range",
    "purchase_timeline",
    "integrations",
    "notes",
    "declined_fields",
    "asked_demo",
    "freebie_only",
    "score",
    "grade",
    "source_channel",
)


def lead_to_dict(lead: Lead) -> dict[str, Any]:
    return {f: getattr(lead, f) for f in LEAD_SNAPSHOT_FIELDS}


async def get_lead_by_conversation(session: AsyncSession, conversation_id: int) -> Lead | None:
    stmt = select(Lead).where(Lead.conversation_id == conversation_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_create_lead(
    session: AsyncSession,
    user_id: int,
    conversation_id: int,
    source_channel: str | None = None,
) -> Lead:
    lead = await get_lead_by_conversation(session, conversation_id)
    if lead is not None:
        return lead
    stmt = (
        pg_insert(Lead)
        .values(user_id=user_id, conversation_id=conversation_id, source_channel=source_channel)
        .on_conflict_do_nothing(index_elements=["conversation_id"])
        .returning(Lead)
    )
    lead = (await session.execute(stmt)).scalar_one_or_none()
    if lead is not None:
        return lead
    lead = await get_lead_by_conversation(session, conversation_id)
    assert lead is not None
    return lead


async def update_lead(session: AsyncSession, lead_id: int, values: dict[str, Any]) -> None:
    await session.execute(
        update(Lead).where(Lead.id == lead_id).values(**values, updated_at=func.now())
    )


async def add_audit(
    session: AsyncSession,
    actor_type: str,
    action: str,
    entity_type: str,
    entity_id: int,
    metadata: dict[str, Any],
    actor_id: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            meta=metadata,
        )
    )


async def stale_replied_ids(session: AsyncSession, stale_seconds: int = 300) -> list[int]:
    """兜底扫描器③：replied 超时（extract_lead 任务丢失）→ 补 enqueue（§6）。"""
    deadline = datetime.now(UTC) - timedelta(seconds=stale_seconds)
    stmt = select(TelegramUpdate.update_id).where(
        TelegramUpdate.status == "replied", TelegramUpdate.picked_at < deadline
    )
    return [row[0] for row in (await session.execute(stmt)).fetchall()]


async def create_integration_job(
    session: AsyncSession,
    integration_type: str,
    entity_type: str,
    entity_id: int,
    idempotency_key: str,
    payload: dict[str, Any],
) -> int | None:
    """版本化幂等键（§11）：新建返回 job id，已存在返回 None。"""
    stmt = (
        pg_insert(IntegrationJob)
        .values(
            integration_type=integration_type,
            entity_type=entity_type,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(IntegrationJob.id)
    )
    row = (await session.execute(stmt)).first()
    return row[0] if row else None


# ---------- handoffs（§9，M6） ----------


async def create_handoff(
    session: AsyncSession,
    conversation_id: int,
    reason: str,
    resolved: bool = False,
    operator_id: int | None = None,
) -> bool:
    """未解决记录受 one_unresolved_handoff 部分唯一索引约束（并发幂等）；
    通知型记录创建即 resolved，不受该索引限制。"""
    values: dict[str, Any] = {
        "conversation_id": conversation_id,
        "reason": reason,
        "operator_id": operator_id,
    }
    if resolved:
        values["resolved_at"] = func.now()
        await session.execute(pg_insert(Handoff).values(**values))
        return True
    stmt = (
        pg_insert(Handoff)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["conversation_id"], index_where=text("resolved_at IS NULL")
        )
    )
    result = await session.execute(stmt)
    return bool(cast(CursorResult[Any], result).rowcount)


async def get_unresolved_handoff(session: AsyncSession, conversation_id: int) -> Handoff | None:
    stmt = select(Handoff).where(
        Handoff.conversation_id == conversation_id, Handoff.resolved_at.is_(None)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def accept_unresolved_handoff(
    session: AsyncSession, conversation_id: int, operator_id: int
) -> None:
    await session.execute(
        update(Handoff)
        .where(Handoff.conversation_id == conversation_id, Handoff.resolved_at.is_(None))
        .values(accepted_at=func.now(), operator_id=operator_id)
    )


async def resolve_unresolved_handoff(
    session: AsyncSession, conversation_id: int, operator_id: int
) -> None:
    await session.execute(
        update(Handoff)
        .where(Handoff.conversation_id == conversation_id, Handoff.resolved_at.is_(None))
        .values(resolved_at=func.now(), operator_id=func.coalesce(Handoff.operator_id, operator_id))
    )


async def claim_integration_job(session: AsyncSession, job_id: int) -> IntegrationJob | None:
    """原子抢占：仅 pending 可进入 running（与扫描器④的重置闭环，§11）。"""
    stmt = (
        update(IntegrationJob)
        .where(IntegrationJob.id == job_id, IntegrationJob.status == "pending")
        .values(status="running", picked_at=func.now(), updated_at=func.now())
        .returning(IntegrationJob)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def complete_integration_job(session: AsyncSession, job_id: int) -> None:
    await session.execute(
        update(IntegrationJob)
        .where(IntegrationJob.id == job_id)
        .values(status="done", completed_at=func.now(), updated_at=func.now(), last_error=None)
    )


async def retry_integration_job(
    session: AsyncSession, job_id: int, attempts: int, error: str, delay_seconds: int
) -> None:
    """失败退避（§11）：回到 pending 并设 next_retry_at，等待重入队/扫描器兜底。"""
    next_retry = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    await session.execute(
        update(IntegrationJob)
        .where(IntegrationJob.id == job_id)
        .values(
            status="pending",
            attempts=attempts,
            last_error=error,
            next_retry_at=next_retry,
            picked_at=None,
            updated_at=func.now(),
        )
    )


async def fail_integration_job(
    session: AsyncSession, job_id: int, attempts: int, error: str
) -> None:
    await session.execute(
        update(IntegrationJob)
        .where(IntegrationJob.id == job_id)
        .values(
            status="failed",
            attempts=attempts,
            last_error=error,
            picked_at=None,
            updated_at=func.now(),
        )
    )


async def reset_expired_running_jobs(session: AsyncSession, lease_minutes: int = 10) -> list[int]:
    """兜底扫描器④：running 超时（worker 崩溃）原子重置为 pending，返回待入队 ID（§6/§11）。"""
    deadline = datetime.now(UTC) - timedelta(minutes=lease_minutes)
    stmt = (
        update(IntegrationJob)
        .where(IntegrationJob.status == "running", IntegrationJob.picked_at < deadline)
        .values(status="pending", picked_at=None, updated_at=func.now())
        .returning(IntegrationJob.id)
    )
    return [row[0] for row in (await session.execute(stmt)).fetchall()]


async def stale_pending_job_ids(session: AsyncSession, grace_seconds: int = 300) -> list[int]:
    """兜底扫描器④'：pending 但入队丢失（新建未消费 / 退避到期未重入队）→ 补 enqueue。"""
    now = datetime.now(UTC)
    deadline = now - timedelta(seconds=grace_seconds)
    stmt = select(IntegrationJob.id).where(
        IntegrationJob.status == "pending",
        ((IntegrationJob.next_retry_at.is_(None)) & (IntegrationJob.created_at < deadline))
        | (IntegrationJob.next_retry_at < deadline),
    )
    return [row[0] for row in (await session.execute(stmt)).fetchall()]


async def get_lead(session: AsyncSession, lead_id: int) -> Lead | None:
    return await session.get(Lead, lead_id)


async def cleanup_expired_data(session: AsyncSession, retention_days: int) -> dict[str, int]:
    """数据保留期清理（§14）：删除超期的 telegram_updates 与已关闭超期会话（级联）。"""
    from sqlalchemy import delete

    deadline = datetime.now(UTC) - timedelta(days=retention_days)
    updates_result = await session.execute(
        delete(TelegramUpdate).where(TelegramUpdate.received_at < deadline)
    )
    convs_result = await session.execute(
        delete(Conversation).where(
            Conversation.status == "closed", Conversation.closed_at < deadline
        )
    )
    return {
        "updates": cast(CursorResult[Any], updates_result).rowcount,
        "conversations": cast(CursorResult[Any], convs_result).rowcount,
    }


async def delete_user_data(session: AsyncSession, telegram_user_id: int) -> dict[str, int] | None:
    """按 Telegram user ID 删除用户数据（§14）。

    内容表靠 DDL 级联（users→conversations→messages/handoffs、users→leads）；
    integration_jobs（无外键）与 audit_logs 中相关 entity 的记录（metadata 含
    lead 字段新旧值）显式清理；删除动作本身由调用方另记匿名 audit。
    返回 None 表示用户不存在。
    """
    from sqlalchemy import delete

    user = (
        await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    ).scalar_one_or_none()
    if user is None:
        return None

    lead_ids = [
        row[0]
        for row in (await session.execute(select(Lead.id).where(Lead.user_id == user.id))).all()
    ]
    conv_ids = [
        row[0]
        for row in (
            await session.execute(select(Conversation.id).where(Conversation.user_id == user.id))
        ).all()
    ]

    jobs_removed = 0
    audits_removed = 0
    if lead_ids:
        result = await session.execute(
            delete(IntegrationJob).where(
                IntegrationJob.entity_type == "lead", IntegrationJob.entity_id.in_(lead_ids)
            )
        )
        jobs_removed = cast(CursorResult[Any], result).rowcount
        result = await session.execute(
            delete(AuditLog).where(AuditLog.entity_type == "lead", AuditLog.entity_id.in_(lead_ids))
        )
        audits_removed += cast(CursorResult[Any], result).rowcount
    if conv_ids:
        result = await session.execute(
            delete(AuditLog).where(
                AuditLog.entity_type == "conversation", AuditLog.entity_id.in_(conv_ids)
            )
        )
        audits_removed += cast(CursorResult[Any], result).rowcount

    await session.delete(user)  # 级联 conversations/messages/handoffs/leads
    return {
        "leads": len(lead_ids),
        "conversations": len(conv_ids),
        "integration_jobs": jobs_removed,
        "audit_logs": audits_removed,
    }


async def claim_replied_update(session: AsyncSession, update_id: int) -> dict[str, Any] | None:
    """extract_lead 原子抢占（第三轮评审）：replied → extracting，并发任务只有一个能通过。"""
    stmt = (
        update(TelegramUpdate)
        .where(TelegramUpdate.update_id == update_id, TelegramUpdate.status == "replied")
        .values(status="extracting", picked_at=func.now())
        .returning(TelegramUpdate.payload)
    )
    row = (await session.execute(stmt)).first()
    return row[0] if row else None


async def reset_expired_extracting(session: AsyncSession, lease_minutes: int = 5) -> list[int]:
    """兜底扫描器③'：extracting 租约过期（worker 崩溃）→ 原子重置回 replied，返回待入队 ID。"""
    deadline = datetime.now(UTC) - timedelta(minutes=lease_minutes)
    stmt = (
        update(TelegramUpdate)
        .where(TelegramUpdate.status == "extracting", TelegramUpdate.picked_at < deadline)
        .values(status="replied", picked_at=func.now())
        .returning(TelegramUpdate.update_id)
    )
    return [row[0] for row in (await session.execute(stmt)).fetchall()]


async def has_earlier_pending_update(
    session: AsyncSession, chat_id: int, before_update_id: int
) -> bool:
    """同 chat 是否存在更早的未完成 update（第三轮评审：会话内按序处理的守卫）。

    chat id 必须按 BIGINT 处理：现代 Telegram 的 user/chat id 已超出 int32
    （如 7606380623），as_integer() 的 INTEGER cast 会在真实用户上直接报错。
    """
    stmt = (
        select(func.count())
        .select_from(TelegramUpdate)
        .where(
            TelegramUpdate.update_id < before_update_id,
            TelegramUpdate.status.in_(["queued", "processing"]),
            sa_cast(TelegramUpdate.payload["message"]["chat"]["id"].as_string(), BigInteger)
            == chat_id,
        )
    )
    return bool((await session.execute(stmt)).scalar())
