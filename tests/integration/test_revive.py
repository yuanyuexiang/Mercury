"""沉睡线索唤醒：触发矩阵 + 防骚扰幂等（revive_count 持久上限）。"""

from datetime import UTC, datetime, timedelta

from domain import repositories
from domain.models import Conversation, Lead, Message
from domain.orchestrator import run_revive_leads
from sqlalchemy import select, update


async def _seed(
    session_factory,
    tg_id: int,
    *,
    grade: str,
    lead_status: str = "open",
    conv_status: str = "ai_active",
    quiet_days: int = 5,
) -> int:
    """造一条指定状态的线索 + 会话，返回 lead_id。"""
    async with session_factory() as session:
        user = await repositories.upsert_user(session, {"id": tg_id, "username": f"u{tg_id}"})
        conv = await repositories.get_or_create_open_conversation(session, tg_id, user.id)
        conv.status = conv_status
        lead = Lead(conversation_id=conv.id, user_id=user.id, grade=grade, status=lead_status)
        session.add(lead)
        await session.flush()
        lead_id = lead.id
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conv.id)
            .values(last_message_at=datetime.now(UTC) - timedelta(days=quiet_days))
        )
        await session.commit()
    return lead_id


async def test_revive_matrix_and_idempotency(session_factory, sender) -> None:
    # 该唤醒的：安静 5 天的 medium/high + open + ai_active
    lead_medium = await _seed(session_factory, 91001, grade="medium")
    await _seed(session_factory, 91002, grade="high")
    # 不该唤醒的：低意向 / 人工接管中 / 已成交 / 最近还活跃
    await _seed(session_factory, 91003, grade="low")
    await _seed(session_factory, 91004, grade="high", conv_status="human_active")
    await _seed(session_factory, 91005, grade="high", lead_status="won")
    await _seed(session_factory, 91006, grade="high", quiet_days=0)

    sent = await run_revive_leads(session_factory, sender, after_days=3, brand_name="Acme")
    assert sent == 2
    assert len(sender.sent) == 2
    assert "Acme" in sender.sent[0][1] and "demo" in sender.sent[0][1]

    async with session_factory() as session:
        lead = await session.get(Lead, lead_medium)
        assert lead is not None and lead.revive_count == 1 and lead.last_revived_at is not None
        msg = (
            await session.execute(
                select(Message).where(
                    Message.conversation_id == lead.conversation_id,
                    Message.direction == "outbound",
                )
            )
        ).scalar_one()
        assert msg.sender_type == "system" and msg.delivery_status == "sent"

    # 幂等：再跑一次，revive_count 已达上限（默认 1），一条都不再发
    sent = await run_revive_leads(session_factory, sender, after_days=3)
    assert sent == 0 and len(sender.sent) == 2

    # 上限放宽到 2：会话仍安静（唤醒时 touch 了 last_message_at，需再次沉睡才触发）
    sent = await run_revive_leads(session_factory, sender, after_days=3, max_attempts=2)
    assert sent == 0  # touch_last_message 刷新了活跃时间，未到再次沉睡门槛
