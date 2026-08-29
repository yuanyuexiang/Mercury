"""人工接管状态机（技术方案 §9）：transition() 单一入口，非法迁移抛异常。

静默型触发（user_request / sensitive / manual）→ handoff_pending：AI 只发一次确认，
此后新消息仅转通知；通知型触发（low_confidence / high_intent）只写 handoffs 记录
不改会话状态，创建即 resolved（不占 one_unresolved_handoff 部分唯一索引）。
"""

from typing import Literal

import structlog
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain import repositories
from domain.models import Conversation

logger = structlog.get_logger()

# MVP 单管理员恒为 1（内部 ID，非 Telegram ID；P1 建 operators 表，§9）
OPERATOR_ID = 1

SILENT_REASONS = ("user_request", "sensitive", "manual")
NOTIFY_REASONS = ("low_confidence", "high_intent")

# AI 静默的会话状态（§9：handoff_pending 一次确认后静默，human_active 完全静默）
SILENT_STATUSES = ("handoff_pending", "human_active")

Event = Literal["request_human", "accept", "resume_ai", "close"]


class HandoffError(Exception):
    """非法状态迁移。"""


_TRANSITIONS: dict[tuple[str, str], str] = {
    ("ai_active", "request_human"): "handoff_pending",
    ("handoff_pending", "accept"): "human_active",
    ("handoff_pending", "resume_ai"): "ai_active",
    ("human_active", "resume_ai"): "ai_active",
    ("ai_active", "close"): "closed",
    ("handoff_pending", "close"): "closed",
    ("human_active", "close"): "closed",
}


def next_status(current: str, event: str) -> str:
    """纯函数迁移表：单元测试可穷举全部合法/非法组合。"""
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError:
        raise HandoffError(f"非法状态迁移：{current} --{event}-->") from None


async def transition(
    session: AsyncSession,
    conversation: Conversation,
    event: Event,
    *,
    reason: str | None = None,
    operator_id: int = OPERATOR_ID,
) -> str:
    """唯一状态变更入口（§9）：更新会话状态、维护 handoffs 记录、写 audit。"""
    old_status = conversation.status
    new_status = next_status(old_status, event)

    values: dict[str, object] = {"status": new_status}
    if event == "close":
        values["closed_at"] = func.now()
    if event == "accept":
        values["assigned_operator_id"] = operator_id
    await session.execute(
        update(Conversation).where(Conversation.id == conversation.id).values(**values)
    )

    if event == "request_human":
        if reason not in SILENT_REASONS:
            raise HandoffError(f"request_human 需要静默型 reason，收到 {reason!r}")
        await repositories.create_handoff(session, conversation.id, reason, resolved=False)
        actor = "system"
    elif event == "accept":
        # 管理员接管：回填 accepted_at（接管确认与"是否停 AI"解耦——停 AI 由状态决定，§9）
        await repositories.accept_unresolved_handoff(session, conversation.id, operator_id)
        actor = "admin"
    else:  # resume_ai / close：了结未解决的接管请求
        await repositories.resolve_unresolved_handoff(session, conversation.id, operator_id)
        actor = "admin"

    await repositories.add_audit(
        session,
        actor_type=actor,
        action=f"conversation_{event}",
        entity_type="conversation",
        entity_id=conversation.id,
        metadata={"from": old_status, "to": new_status, "reason": reason},
    )
    logger.info(
        "handoff_transition",
        conversation_id=conversation.id,
        handoff_event=event,  # 不能叫 event：与 structlog 的事件名参数冲突
        from_status=old_status,
        to_status=new_status,
        reason=reason,
    )
    return new_status


async def notify_only(session: AsyncSession, conversation_id: int, reason: str) -> None:
    """通知型触发（§9）：写 handoffs 记录并创建即 resolved，会话保持 ai_active。"""
    if reason not in NOTIFY_REASONS:
        raise HandoffError(f"notify_only 需要通知型 reason，收到 {reason!r}")
    await repositories.create_handoff(session, conversation_id, reason, resolved=True)
