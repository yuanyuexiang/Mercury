"""指标后台 API（技术方案 §10）：概览、成本（token）、知识缺口。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from domain.models import Conversation, Handoff, Lead, Message
from fastapi import APIRouter, Request
from sqlalchemy import Select, func, select

from api.deps import AdminRead

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

WINDOW_DAYS = 14


def _since() -> datetime:
    return datetime.now(UTC) - timedelta(days=WINDOW_DAYS)


async def _count(session: Any, stmt: Select[Any]) -> int:
    return int((await session.execute(stmt)).scalar() or 0)


@router.get("/overview", dependencies=AdminRead)
async def overview(request: Request) -> dict[str, Any]:
    since = _since()
    async with request.app.state.session_factory() as session:
        messages = await _count(
            session, select(func.count()).select_from(Message).where(Message.created_at >= since)
        )
        conversations = await _count(
            session,
            select(func.count()).select_from(Conversation).where(Conversation.started_at >= since),
        )
        auto_replies = await _count(
            session,
            select(func.count())
            .select_from(Message)
            .where(
                Message.created_at >= since,
                Message.direction == "outbound",
                Message.sender_type == "ai",
                Message.answer_status == "answered",
            ),
        )
        refused = await _count(
            session,
            select(func.count())
            .select_from(Message)
            .where(Message.created_at >= since, Message.answer_status == "refused"),
        )
        handoffs = await _count(
            session,
            select(func.count()).select_from(Handoff).where(Handoff.requested_at >= since),
        )
        leads_total = await _count(session, select(func.count()).select_from(Lead))
        leads_high = await _count(
            session, select(func.count()).select_from(Lead).where(Lead.grade == "high")
        )
    return {
        "window_days": WINDOW_DAYS,
        "messages": messages,
        "conversations": conversations,
        "auto_replies": auto_replies,
        "refused": refused,
        "handoffs": handoffs,
        "leads_total": leads_total,
        "leads_high": leads_high,
    }


@router.get("/costs", dependencies=AdminRead)
async def costs(request: Request) -> dict[str, Any]:
    """按日 token 汇总（§10）；单价随模型/供应商变动，估算成本由前端按需换算。"""
    since = _since()
    async with request.app.state.session_factory() as session:
        rows = (
            await session.execute(
                select(
                    func.date_trunc("day", Message.created_at).label("day"),
                    Message.model_name,
                    func.sum(func.coalesce(Message.prompt_tokens, 0)),
                    func.sum(func.coalesce(Message.completion_tokens, 0)),
                    func.count(),
                )
                .where(Message.created_at >= since, Message.model_name.is_not(None))
                .group_by("day", Message.model_name)
                .order_by("day")
            )
        ).all()
    return {
        "items": [
            {
                "day": day.date().isoformat(),
                "model": model,
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "calls": int(calls),
            }
            for day, model, prompt, completion, calls in rows
        ]
    }


@router.get("/knowledge-gaps", dependencies=AdminRead)
async def knowledge_gaps(request: Request) -> dict[str, Any]:
    """知识缺口（§5.2）：拒答回复关联到触发它的用户问题。"""
    async with request.app.state.session_factory() as session:
        refused = (
            (
                await session.execute(
                    select(Message)
                    .where(Message.answer_status == "refused", Message.direction == "outbound")
                    .order_by(Message.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        items = []
        for m in refused:
            question = None
            if m.source_update_id is not None:
                inbound = (
                    await session.execute(
                        select(Message).where(
                            Message.source_update_id == m.source_update_id,
                            Message.direction == "inbound",
                        )
                    )
                ).scalar_one_or_none()
                question = inbound.content if inbound else None
            items.append(
                {
                    "question": question,
                    "conversation_id": m.conversation_id,
                    "refused_at": m.created_at.isoformat(),
                }
            )
    return {"items": items}
