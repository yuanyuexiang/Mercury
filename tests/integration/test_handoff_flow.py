"""§9 接管流程：静默（100% 验收项）、/human 幂等、敏感触发、接管/恢复、通知型记录。"""

import pytest
from domain import handoff, repositories
from domain.models import AuditLog, Conversation, Handoff, Message, TelegramUpdate
from domain.orchestrator import run_process_update
from domain.schemas import TriageResult
from sqlalchemy import select

from tests.conftest import tg_update


async def _send(session_factory, locker, sender, brain, uid: int, text: str | None) -> str:
    async with session_factory() as session:
        await repositories.insert_update(session, uid, tg_update(uid, text))
        await session.commit()
    return await run_process_update(session_factory, locker, sender, brain, uid)


async def _get_conv(session_factory) -> Conversation:
    async with session_factory() as session:
        return (await session.execute(select(Conversation))).scalar_one()


async def _transition(session_factory, event: str, reason: str | None = None) -> None:
    async with session_factory() as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        await handoff.transition(session, conv, event, reason=reason)  # type: ignore[arg-type]
        await session.commit()


async def test_human_active_ai_stays_silent(session_factory, locker, sender, brain) -> None:
    """M6 验收标准：human_active 下 AI 静默——inbound 落库、只转通知、绝无 AI 回复。"""
    await _send(session_factory, locker, sender, brain, 501, "你好")  # 正常回答
    await _send(session_factory, locker, sender, brain, 502, "/human")
    await _transition(session_factory, "accept")
    assert (await _get_conv(session_factory)).status == "human_active"

    sent_before = len(sender.sent)
    triage_before = len(brain.triage_calls)
    assert (
        await run_process_update(
            session_factory,
            locker,
            sender,
            brain,
            await _seed_raw(session_factory, 503, "还在吗？"),
        )
        == "done"
    )

    assert len(sender.sent) == sent_before, "human_active 下绝不能有 AI 回复"
    assert len(brain.triage_calls) == triage_before, "不应调用任何 LLM"
    assert any("用户有新消息" in n for n in sender.notices)
    async with session_factory() as session:
        inbound = (
            await session.execute(select(Message).where(Message.content == "还在吗？"))
        ).scalar_one()
        assert inbound.direction == "inbound"  # 消息不丢
        row = (
            await session.execute(select(TelegramUpdate).where(TelegramUpdate.update_id == 503))
        ).scalar_one()
        assert row.status == "done"


async def _seed_raw(session_factory, uid: int, text: str | None) -> int:
    async with session_factory() as session:
        await repositories.insert_update(session, uid, tg_update(uid, text))
        await session.commit()
    return uid


async def test_handoff_pending_silent_after_ack(session_factory, locker, sender, brain) -> None:
    """handoff_pending：/human 确认一次后，后续消息只转通知。"""
    await _send(session_factory, locker, sender, brain, 511, "/human")
    assert (await _get_conv(session_factory)).status == "handoff_pending"
    sent_before = len(sender.sent)
    await _send(session_factory, locker, sender, brain, 512, "快点啊")
    assert len(sender.sent) == sent_before
    assert any("用户有新消息" in n for n in sender.notices)


async def test_human_command_transitions_and_records(
    session_factory, locker, sender, brain
) -> None:
    await _send(session_factory, locker, sender, brain, 521, "/human")
    conv = await _get_conv(session_factory)
    assert conv.status == "handoff_pending"
    assert any("已通知人工" in text for _, text in sender.sent)
    async with session_factory() as session:
        h = (await session.execute(select(Handoff))).scalar_one()
        assert h.reason == "user_request" and h.resolved_at is None and h.accepted_at is None
        audit = (
            await session.execute(
                select(AuditLog).where(AuditLog.action == "conversation_request_human")
            )
        ).scalar_one()
        assert audit.meta["to"] == "handoff_pending"


async def test_human_command_idempotent(session_factory, locker, sender, brain) -> None:
    """重复 /human：只回确认文案，不产生第二条未解决 handoff（第二轮评审修复项）。"""
    await _send(session_factory, locker, sender, brain, 531, "/human")
    await _send(session_factory, locker, sender, brain, 532, "/human")
    assert any("在赶来的路上" in text for _, text in sender.sent)
    assert (await _get_conv(session_factory)).status == "handoff_pending"
    async with session_factory() as session:
        handoffs = (await session.execute(select(Handoff))).scalars().all()
    assert len(handoffs) == 1


async def test_sensitive_risk_enters_pending_then_silent(
    session_factory, locker, sender, brain
) -> None:
    """敏感触发 = 静默型：进入 handoff_pending（一次模板确认），后续消息静默。"""
    brain.triage_result = TriageResult(risk="payment", needs_rag=True)
    await _send(session_factory, locker, sender, brain, 541, "我要退款")
    conv = await _get_conv(session_factory)
    assert conv.status == "handoff_pending"
    async with session_factory() as session:
        h = (await session.execute(select(Handoff))).scalar_one()
        assert h.reason == "sensitive" and h.resolved_at is None

    sent_before = len(sender.sent)
    brain.triage_result = TriageResult()  # 即使后续 triage 无风险，静默态也不该再进 LLM
    await _send(session_factory, locker, sender, brain, 542, "怎么退")
    assert len(sender.sent) == sent_before


async def test_accept_and_resume_cycle(session_factory, locker, sender, brain) -> None:
    """接管回填 accepted_at/operator，恢复 AI 后重新接待。"""
    await _send(session_factory, locker, sender, brain, 551, "/human")
    await _transition(session_factory, "accept")
    conv = await _get_conv(session_factory)
    assert conv.status == "human_active" and conv.assigned_operator_id == handoff.OPERATOR_ID
    async with session_factory() as session:
        h = (await session.execute(select(Handoff))).scalar_one()
        assert h.accepted_at is not None and h.operator_id == handoff.OPERATOR_ID

    await _transition(session_factory, "resume_ai")
    assert (await _get_conv(session_factory)).status == "ai_active"
    async with session_factory() as session:
        h = (await session.execute(select(Handoff))).scalar_one()
        assert h.resolved_at is not None

    await _send(session_factory, locker, sender, brain, 552, "在吗")
    assert sender.sent[-1][1] == "回答：在吗"  # AI 恢复接待


async def test_low_confidence_is_notify_only(session_factory, locker, sender, brain) -> None:
    """拒答 → 通知型记录：创建即 resolved，会话保持 ai_active。"""
    brain.refuse = True
    await _send(session_factory, locker, sender, brain, 561, "冷门问题")
    assert (await _get_conv(session_factory)).status == "ai_active"
    async with session_factory() as session:
        h = (await session.execute(select(Handoff))).scalar_one()
        assert h.reason == "low_confidence" and h.resolved_at is not None


async def test_illegal_transition_raises(session_factory, locker, sender, brain) -> None:
    await _send(session_factory, locker, sender, brain, 571, "hi")
    async with session_factory() as session:
        conv = (await session.execute(select(Conversation))).scalar_one()
        with pytest.raises(handoff.HandoffError):
            await handoff.transition(session, conv, "accept")  # ai_active 不能直接 accept
