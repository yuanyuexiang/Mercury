"""§6 管线：RAG 回答闭环、原子抢占、两阶段投递幂等、/reset、非文本、异常兜底。"""

from domain import repositories
from domain.models import Conversation, Message, TelegramUpdate, User
from domain.orchestrator import run_process_update
from sqlalchemy import func, select

from tests.conftest import tg_update


async def _seed(session_factory, payload) -> int:
    async with session_factory() as session:
        await repositories.insert_update(session, payload["update_id"], payload)
        await session.commit()
    return payload["update_id"]


async def test_answer_roundtrip(session_factory, locker, sender, brain) -> None:
    """闭环：user/conversation/inbound 落库，RAG 回答经两阶段送达，来源与记账写入。"""
    uid = await _seed(session_factory, tg_update(101, "你好"))
    outcome = await run_process_update(session_factory, locker, sender, brain, uid)
    assert outcome == "done"
    assert sender.sent == [(1000, "回答：你好")]
    assert brain.triage_calls and brain.answer_calls == ["你好"]

    async with session_factory() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.telegram_user_id == 500
        conv = (await session.execute(select(Conversation))).scalar_one()
        assert conv.status == "ai_active" and conv.last_message_at is not None

        inbound = (
            await session.execute(select(Message).where(Message.direction == "inbound"))
        ).scalar_one()
        assert inbound.content == "你好" and inbound.source_update_id == uid

        outbound = (
            await session.execute(select(Message).where(Message.direction == "outbound"))
        ).scalar_one()
        assert outbound.delivery_status == "sent"
        assert outbound.delivery_key == f"reply:{uid}"
        assert outbound.answer_status == "answered"
        assert outbound.source_chunk_ids == [1, 2]
        assert outbound.model_name == "fake-model"
        assert outbound.prompt_tokens == 100 and outbound.latency_ms == 42

        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "done" and row.processed_at is not None


async def test_rerun_is_noop(session_factory, locker, sender, brain) -> None:
    """原子抢占：done 后再跑同一 update → duplicate，不重发。"""
    uid = await _seed(session_factory, tg_update(102, "hi"))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "duplicate"
    assert len(sender.sent) == 1


async def test_sending_residue_marks_uncertain(session_factory, locker, sender, brain) -> None:
    """重试遇 'sending' 残留 → 标 uncertain 不重发，通知运营者（§6 第 4 步）。"""
    uid = await _seed(session_factory, tg_update(103, "again"))
    async with session_factory() as session:
        user = await repositories.upsert_user(session, {"id": 500, "first_name": "Test"})
        conv = await repositories.get_or_create_open_conversation(session, 1000, user.id)
        state, _ = await repositories.create_outbound_sending(
            session, conv.id, uid, f"reply:{uid}", "回答：again"
        )
        assert state == "created"
        await session.commit()

    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert sender.sent == []
    assert any("投递结果不明" in n for n in sender.notices)
    async with session_factory() as session:
        outbound = (
            await session.execute(select(Message).where(Message.delivery_key == f"reply:{uid}"))
        ).scalar_one()
        assert outbound.delivery_status == "uncertain"


async def test_reset_creates_new_conversation(session_factory, locker, sender, brain) -> None:
    """/reset：关旧建新（不经 LLM）。"""
    await run_process_update(
        session_factory, locker, sender, brain, await _seed(session_factory, tg_update(104, "hi"))
    )
    await run_process_update(
        session_factory,
        locker,
        sender,
        brain,
        await _seed(session_factory, tg_update(105, "/reset")),
    )
    async with session_factory() as session:
        convs = (await session.execute(select(Conversation))).scalars().all()
    assert len(convs) == 2
    assert sorted(c.status for c in convs) == ["ai_active", "closed"]
    assert brain.answer_calls == ["hi"], "/reset 不应触发 LLM"


async def test_non_text_skipped_with_notice(session_factory, locker, sender, brain) -> None:
    """非文本消息：固定文案 + status=skipped，不经 LLM（§5）。"""
    uid = await _seed(session_factory, tg_update(106, None))
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "done"
    assert len(sender.sent) == 1 and "仅支持文字" in sender.sent[0][1]
    assert brain.triage_calls == []
    async with session_factory() as session:
        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "skipped"


async def test_failure_marks_failed_and_sends_fallback(session_factory, locker, brain) -> None:
    """发送失败：update failed + 兜底文案走统一投递 + 通知运营者（§6 第 6 步）。"""

    class FlakySender:
        def __init__(self) -> None:
            self.calls = 0
            self.notices: list[str] = []

        async def send_message(self, chat_id: int, text: str) -> int:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("telegram down")
            return 999

        async def notify_operator(self, text: str) -> None:
            self.notices.append(text)

    flaky = FlakySender()
    uid = await _seed(session_factory, tg_update(107, "boom"))
    assert await run_process_update(session_factory, locker, flaky, brain, uid) == "failed"
    assert flaky.calls == 2  # 第 1 次正文失败，第 2 次兜底文案成功
    assert any("处理失败" in n for n in flaky.notices)
    async with session_factory() as session:
        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "failed" and row.error is not None
        n_outbound = (
            await session.execute(
                select(func.count()).select_from(Message).where(Message.direction == "outbound")
            )
        ).scalar()
        assert n_outbound == 2  # 失败的正文（failed）+ 兜底（sent）


async def test_ordering_guard_defers_newer_update(session_factory, locker, sender, brain) -> None:
    """第三轮评审：同 chat 有更早未完成 update → 新消息让位，保证会话内按序处理。"""
    await _seed(session_factory, tg_update(150, "第一条"))
    await _seed(session_factory, tg_update(151, "第二条"))

    # 先处理新的 → 应让位（第一条还是 queued）
    assert await run_process_update(session_factory, locker, sender, brain, 151) == "locked"
    assert sender.sent == []

    assert await run_process_update(session_factory, locker, sender, brain, 150) == "done"
    assert await run_process_update(session_factory, locker, sender, brain, 151) == "done"
    assert [t for _, t in sender.sent] == ["回答：第一条", "回答：第二条"]
