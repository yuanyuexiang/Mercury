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


@router.get("/pending", dependencies=AdminRead)
async def pending(request: Request) -> dict[str, int]:
    """待接管数（侧边栏 badge 轮询用，保持轻量）。"""
    async with request.app.state.session_factory() as session:
        n = await _count(
            session,
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.status == "handoff_pending"),
        )
    return {"pending_handoffs": n}


@router.get("/overview", dependencies=AdminRead)
async def overview(request: Request, tz_offset_minutes: int = 0) -> dict[str, Any]:
    """概览：窗口统计 + 获客漏斗 + 今日数字（按前端时区界定"今日"）+ 14 天趋势。"""
    since = _since()
    local_now = datetime.now(UTC) + timedelta(minutes=tz_offset_minutes)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        minutes=tz_offset_minutes
    )
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
        pending_handoffs = await _count(
            session,
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.status == "handoff_pending"),
        )
        # 获客漏斗（窗口内）：会话 → 产生线索 → 高意向 → 已同步 CRM
        leads_window = await _count(
            session, select(func.count()).select_from(Lead).where(Lead.created_at >= since)
        )
        leads_high_window = await _count(
            session,
            select(func.count())
            .select_from(Lead)
            .where(Lead.created_at >= since, Lead.grade == "high"),
        )
        leads_synced_window = await _count(
            session,
            select(func.count())
            .select_from(Lead)
            .where(Lead.created_at >= since, Lead.external_crm_id.is_not(None)),
        )
        # 今日（前端本地时区口径）
        today_conversations = await _count(
            session,
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.started_at >= today_start),
        )
        today_leads = await _count(
            session, select(func.count()).select_from(Lead).where(Lead.created_at >= today_start)
        )
        # 近 14 天趋势：会话 vs 新线索（按前端本地时区分日）
        day_expr = func.date_trunc(
            "day", Conversation.started_at + timedelta(minutes=tz_offset_minutes)
        )
        conv_rows = (
            await session.execute(
                select(day_expr.label("day"), func.count())
                .where(Conversation.started_at >= since)
                .group_by("day")
            )
        ).all()
        lead_day_expr = func.date_trunc(
            "day", Lead.created_at + timedelta(minutes=tz_offset_minutes)
        )
        lead_rows = (
            await session.execute(
                select(lead_day_expr.label("day"), func.count())
                .where(Lead.created_at >= since)
                .group_by("day")
            )
        ).all()
    trend: dict[str, dict[str, int]] = {}
    for day, n in conv_rows:
        trend.setdefault(day.date().isoformat(), {"conversations": 0, "leads": 0})[
            "conversations"
        ] = int(n)
    for day, n in lead_rows:
        trend.setdefault(day.date().isoformat(), {"conversations": 0, "leads": 0})["leads"] = int(n)
    return {
        "window_days": WINDOW_DAYS,
        "messages": messages,
        "conversations": conversations,
        "auto_replies": auto_replies,
        "refused": refused,
        "handoffs": handoffs,
        "leads_total": leads_total,
        "leads_high": leads_high,
        "pending_handoffs": pending_handoffs,
        "funnel": {
            "conversations": conversations,
            "leads": leads_window,
            "leads_high": leads_high_window,
            "leads_synced": leads_synced_window,
        },
        "today": {"conversations": today_conversations, "leads": today_leads},
        "trend": [
            {"day": day, **counts} for day, counts in sorted(trend.items(), key=lambda kv: kv[0])
        ],
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
