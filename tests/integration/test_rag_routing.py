"""§6 第 3c–3e 步路由分支：拒答、敏感转人工、闲聊、triage 降级、LLM 未配置。"""

from domain import repositories
from domain.models import Message
from domain.orchestrator import run_process_update
from domain.schemas import TriageResult
from sqlalchemy import select

from tests.conftest import tg_update


async def _seed(session_factory, payload) -> int:
    async with session_factory() as session:
        await repositories.insert_update(session, payload["update_id"], payload)
        await session.commit()
    return payload["update_id"]


async def test_refusal_path(session_factory, locker, sender, brain) -> None:
    """检索不足 → 拒答模板 + answer_status='refused'（知识缺口来源）+ 通知运营者。"""
    brain.refuse = True
    uid = await _seed(session_factory, tg_update(301, "你们支持量子计算吗"))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert len(sender.sent) == 1 and "同事来确认" in sender.sent[0][1]
    assert any("知识库无法回答" in n for n in sender.notices)
    async with session_factory() as session:
        outbound = (
            await session.execute(select(Message).where(Message.direction == "outbound"))
        ).scalar_one()
        assert outbound.answer_status == "refused"


async def test_sensitive_risk_goes_to_human(session_factory, locker, sender, brain) -> None:
    """risk != none → 转人工模板，不进 RAG（§6 第 3c 步）。"""
    brain.triage_result = TriageResult(risk="payment", needs_rag=True)
    uid = await _seed(session_factory, tg_update(302, "我要退款，你们乱扣费"))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert len(sender.sent) == 1 and "人工" in sender.sent[0][1]
    assert brain.answer_calls == [], "敏感问题不应走 RAG"
    assert any("敏感问题" in n and "payment" in n for n in sender.notices)
    async with session_factory() as session:
        outbound = (
            await session.execute(select(Message).where(Message.direction == "outbound"))
        ).scalar_one()
        assert outbound.answer_status == "handoff"


async def test_smalltalk_skips_rag(session_factory, locker, sender, brain) -> None:
    """needs_rag=False → 轻量模板，不检索（§6 第 3e 步）。"""
    brain.triage_result = TriageResult(risk="none", needs_rag=False)
    uid = await _seed(session_factory, tg_update(303, "早上好呀"))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert brain.answer_calls == []
    assert len(sender.sent) == 1 and "客服助手" in sender.sent[0][1]


async def test_triage_failure_defaults_to_rag(session_factory, locker, sender, brain) -> None:
    """triage 失败按默认值继续（needs_rag=True, risk=none），不阻塞回复（§6 第 3c 步）。"""
    brain.raise_on_triage = True
    uid = await _seed(session_factory, tg_update(304, "价格多少"))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert brain.answer_calls == ["价格多少"]
    assert sender.sent == [(1000, "回答：价格多少")]


async def test_english_user_gets_english_refusal(session_factory, locker, sender, brain) -> None:
    """客户可见文案按语言输出（2026-09-01 文案修订）：英文档案用户收到英文拒答，不再中英堆叠。"""
    brain.refuse = True
    async with session_factory() as session:
        await repositories.insert_update(
            session, 219, tg_update(219, "What is your SLA?", language_code="en")
        )
        await session.commit()
    assert await run_process_update(session_factory, locker, sender, brain, 219) == "done"
    reply = sender.sent[0][1]
    assert "teammate" in reply and "同事" not in reply


async def test_answer_failure_refuses_safely(session_factory, locker, sender, brain) -> None:
    """RAG 生成异常 → 拒答路径，不让用户无响应（§6 第 3d 步）。"""
    brain.raise_on_answer = True
    uid = await _seed(session_factory, tg_update(305, "支持私有化吗"))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert len(sender.sent) == 1 and "同事来确认" in sender.sent[0][1]


async def test_no_brain_degrades_safely(session_factory, locker, sender) -> None:
    """LLM 未配置（brain=None）→ 固定降级文案 + 通知，update 仍正常闭环。"""
    uid = await _seed(session_factory, tg_update(306, "hello"))
    assert await run_process_update(session_factory, locker, sender, None, uid) == "done"
    assert len(sender.sent) == 1
    assert any("LLM 未配置" in n for n in sender.notices)


async def test_history_passed_to_brain(session_factory, locker, sender, brain) -> None:
    """多轮对话：triage/answer 拿到含历史的上下文（§6 第 3 步）。"""
    await run_process_update(
        session_factory,
        locker,
        sender,
        brain,
        await _seed(session_factory, tg_update(307, "第一问")),
    )
    await run_process_update(
        session_factory,
        locker,
        sender,
        brain,
        await _seed(session_factory, tg_update(308, "第二问")),
    )
    last_history = brain.triage_calls[-1]
    contents = [m["content"] for m in last_history]
    assert "第一问" in contents and "回答：第一问" in contents and "第二问" in contents
    roles = {m["content"]: m["role"] for m in last_history}
    assert roles["第一问"] == "user" and roles["回答：第一问"] == "assistant"
