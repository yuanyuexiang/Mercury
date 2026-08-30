"""会话后台 API（技术方案 §10）：列表/详情/接管/恢复/人工发消息。"""

from typing import Any

import structlog
from domain import handoff, repositories
from domain.models import Conversation, Handoff, KnowledgeChunk, Lead, Message, User
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import AdminRead, AdminWrite

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
logger = structlog.get_logger()

PAGE_SIZE = 20


def _conv_summary(conv: Conversation, user: User, lead: Lead | None, last: Message | None) -> dict:
    return {
        "id": conv.id,
        "status": conv.status,
        "telegram_chat_id": conv.telegram_chat_id,
        "user": {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "telegram_user_id": user.telegram_user_id,
        },
        "lead_grade": lead.grade if lead else None,
        "lead_score": lead.score if lead else None,
        "last_message": (last.content[:80] if last else None),
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "started_at": conv.started_at.isoformat(),
    }


@router.get("", dependencies=AdminRead)
async def list_conversations(
    request: Request,
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        stmt = select(Conversation).order_by(Conversation.last_message_at.desc().nulls_last())
        if status:
            stmt = stmt.where(Conversation.status == status)
        if q:
            user_ids = (select(User.id).where(User.username.ilike(f"%{q}%"))).scalar_subquery()
            conv_ids = (
                select(Message.conversation_id).where(Message.content.ilike(f"%{q}%"))
            ).scalar_subquery()
            stmt = stmt.where(Conversation.user_id.in_(user_ids) | Conversation.id.in_(conv_ids))
        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        convs = (
            (await session.execute(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)))
            .scalars()
            .all()
        )
        items = []
        for conv in convs:
            user = await session.get(User, conv.user_id)
            assert user is not None
            lead = await repositories.get_lead_by_conversation(session, conv.id)
            last = (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            items.append(_conv_summary(conv, user, lead, last))
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}


@router.get("/{conversation_id}", dependencies=AdminRead)
async def get_conversation(request: Request, conversation_id: int) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404)
        user = await session.get(User, conv.user_id)
        assert user is not None
        lead = await repositories.get_lead_by_conversation(session, conv.id)
        messages = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.conversation_id == conv.id)
                    .order_by(Message.created_at, Message.id)
                )
            )
            .scalars()
            .all()
        )
        chunk_ids = {cid for m in messages for cid in (m.source_chunk_ids or [])}
        chunks: dict[int, dict[str, Any]] = {}
        if chunk_ids:
            rows = (
                await session.execute(
                    select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids))
                )
            ).scalars()
            chunks = {c.id: {"id": c.id, "content": c.content, "metadata": c.meta} for c in rows}
        handoffs = (
            (
                await session.execute(
                    select(Handoff)
                    .where(Handoff.conversation_id == conv.id)
                    .order_by(Handoff.requested_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return {
        "conversation": {
            "id": conv.id,
            "status": conv.status,
            "telegram_chat_id": conv.telegram_chat_id,
            "assigned_operator_id": conv.assigned_operator_id,
            "source_channel": conv.source_channel,
            "started_at": conv.started_at.isoformat(),
        },
        "user": {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "telegram_user_id": user.telegram_user_id,
        },
        "lead": (
            {
                **repositories.lead_to_dict(lead),
                "id": lead.id,
                "score_reasons": lead.score_reasons,
                "version": lead.version,
                "status": lead.status,
            }
            if lead
            else None
        ),
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "sender_type": m.sender_type,
                "content": m.content,
                "answer_status": m.answer_status,
                "delivery_status": m.delivery_status,
                "model_name": m.model_name,
                "latency_ms": m.latency_ms,
                "source_chunks": [
                    chunks[cid] for cid in (m.source_chunk_ids or []) if cid in chunks
                ],
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
        "handoffs": [
            {
                "id": h.id,
                "reason": h.reason,
                "requested_at": h.requested_at.isoformat(),
                "accepted_at": h.accepted_at.isoformat() if h.accepted_at else None,
                "resolved_at": h.resolved_at.isoformat() if h.resolved_at else None,
                "operator_id": h.operator_id,
            }
            for h in handoffs
        ],
    }


@router.post("/{conversation_id}/handoff", dependencies=AdminWrite)
async def take_over(request: Request, conversation_id: int) -> dict[str, str]:
    """管理员接管：ai_active 先 request_human(manual) 再 accept；pending 直接 accept。"""
    async with request.app.state.session_factory() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404)
        try:
            if conv.status == "ai_active":
                await handoff.transition(session, conv, "request_human", reason="manual")
            new_status = await handoff.transition(session, conv, "accept")
            await session.commit()
        except handoff.HandoffError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": new_status}


@router.post("/{conversation_id}/resume-ai", dependencies=AdminWrite)
async def resume_ai(request: Request, conversation_id: int) -> dict[str, str]:
    async with request.app.state.session_factory() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404)
        try:
            new_status = await handoff.transition(session, conv, "resume_ai")
            await session.commit()
        except handoff.HandoffError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": new_status}


class OperatorMessage(BaseModel):
    text: str


@router.post("/{conversation_id}/messages", dependencies=AdminWrite)
async def send_operator_message(
    request: Request, conversation_id: int, body: OperatorMessage
) -> dict[str, Any]:
    """人工发消息（§9）：api 直接调 Telegram，sender_type='operator'。"""
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="消息不能为空")
    async with request.app.state.session_factory() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404)
        try:
            tg_message_id = await request.app.state.sender.send_message(
                conv.telegram_chat_id, body.text
            )
        except Exception as exc:
            logger.exception("operator_message_send_failed", conversation_id=conversation_id)
            raise HTTPException(status_code=502, detail="Telegram 发送失败") from exc
        message = Message(
            conversation_id=conv.id,
            telegram_message_id=tg_message_id,
            direction="outbound",
            sender_type="operator",
            content=body.text,
            delivery_status="sent",
        )
        session.add(message)
        await repositories.touch_last_message(session, conv.id)
        await session.commit()
        return {"id": message.id, "telegram_message_id": tg_message_id}
