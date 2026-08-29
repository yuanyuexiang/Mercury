"""编排管线业务核心（技术方案 §6）：路由只产出 ReplyPlan，统一投递是唯一发送出口。

依赖以 Protocol 结构化注入（MessageSender / ConversationLocker / Brain），
domain 不 import aiogram/arq/redis/openai 实现。
"""

from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain import repositories, texts
from domain.models import Conversation, Message
from domain.schemas import Deadline, PlannedMessage, RagAnswer, ReplyPlan, TriageResult

logger = structlog.get_logger()


class MessageSender(Protocol):
    """integrations.telegram 实现；测试用 FakeSender。"""

    async def send_message(self, chat_id: int, text: str) -> int: ...

    async def notify_operator(self, text: str) -> None: ...


class ConversationLocker(Protocol):
    """integrations.locks 实现（Redis：TTL 60s + token + 续期 + Lua 释放）。"""

    def hold(self, chat_id: int) -> AbstractAsyncContextManager[bool]: ...


class Brain(Protocol):
    """llm.brain.RagBrain 实现；测试用 FakeBrain。None = LLM 未配置，走安全降级。"""

    async def triage(self, history: list[dict[str, str]], deadline: Deadline) -> TriageResult: ...

    async def answer(
        self,
        session: AsyncSession,
        question: str,
        history: list[dict[str, str]],
        language: str,
        deadline: Deadline,
    ) -> RagAnswer: ...


SessionFactory = async_sessionmaker[AsyncSession]

PipelineOutcome = Literal["done", "locked", "duplicate", "failed"]


def _history_from_messages(messages: list[Message]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for m in messages:
        role = "user" if m.direction == "inbound" else "assistant"
        history.append({"role": role, "content": m.content})
    return history


def _route_command(command: str, update_id: int, conversation: Conversation) -> ReplyPlan | None:
    """命令分支（不经 LLM，§6 第 3a 步）。返回 None 表示不是已知命令。"""
    if command == "/start":
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}", text=texts.WELCOME, sender_type="system"
                )
            ]
        )
    if command == "/reset":
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}", text=texts.RESET_DONE, sender_type="system"
                )
            ]
        )
    if command == "/human":
        # TODO(M6): transition(handoff_pending) + handoffs 记录；当前仅通知 + 确认
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}", text=texts.HUMAN_ACK, sender_type="system"
                )
            ],
            notify_operator=f"用户请求人工（会话 {conversation.id}）",
        )
    return None


async def _decide(
    session: AsyncSession,
    brain: Brain | None,
    conversation: Conversation,
    update_id: int,
    text_content: str,
    reply_deadline_s: float,
) -> ReplyPlan:
    """非命令文本的路由（§6 第 3c–3e 步）：triage → RAG/闲聊，全程共享端到端 deadline。"""
    if brain is None:
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.LLM_NOT_CONFIGURED,
                    sender_type="system",
                    answer_status="refused",
                )
            ],
            notify_operator=f"LLM 未配置，会话 {conversation.id} 无法自动回复",
        )

    deadline = Deadline(reply_deadline_s)
    recent = await repositories.get_recent_messages(session, conversation.id)
    history = _history_from_messages(recent)

    try:
        tri = await brain.triage(history, deadline)
    except Exception:
        logger.warning("triage_failed_using_defaults", update_id=update_id)
        tri = TriageResult()  # risk=none, needs_rag=True：宁可多检索，不可漏风险以外的回答

    if tri.risk != "none":
        # TODO(M6): transition(handoff_pending, sensitive)；当前先模板 + 通知
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.SENSITIVE_TO_HUMAN,
                    sender_type="system",
                    answer_status="handoff",
                )
            ],
            notify_operator=f"敏感问题（{tri.risk}）需人工接管，会话 {conversation.id}",
        )

    if not tri.needs_rag:
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}", text=texts.SMALLTALK, sender_type="system"
                )
            ]
        )

    try:
        ans = await brain.answer(session, text_content, history, tri.language, deadline)
    except Exception:
        logger.warning("rag_answer_failed_refusing", update_id=update_id)
        ans = RagAnswer(refused=True)

    if ans.refused or not ans.text:
        # TODO(M6): 写 handoffs(low_confidence) 通知型记录；当前先通知运营者
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.REFUSED_NO_ANSWER,
                    answer_status="refused",
                    model_name=ans.model_name,
                    prompt_tokens=ans.prompt_tokens,
                    completion_tokens=ans.completion_tokens,
                    latency_ms=ans.latency_ms,
                    source_chunk_ids=ans.source_chunk_ids or None,
                )
            ],
            notify_operator=f"知识库无法回答（会话 {conversation.id}）：{text_content[:80]}",
        )

    # TODO(M5): tri.purchase_intent → status='replied' + enqueue extract_lead
    return ReplyPlan(
        messages=[
            PlannedMessage(
                delivery_key=f"reply:{update_id}",
                text=ans.text,
                answer_status="answered",
                model_name=ans.model_name,
                prompt_tokens=ans.prompt_tokens,
                completion_tokens=ans.completion_tokens,
                latency_ms=ans.latency_ms,
                source_chunk_ids=ans.source_chunk_ids or None,
            )
        ]
    )


async def _deliver(
    session: AsyncSession,
    sender: MessageSender,
    conversation: Conversation,
    update_id: int,
    plan: ReplyPlan,
) -> None:
    """统一投递（§6 第 4 步）：两阶段 + delivery_key 幂等，全管线唯一发送出口。"""
    for planned in plan.messages:
        state, message_id = await repositories.create_outbound_sending(
            session,
            conversation_id=conversation.id,
            update_id=update_id,
            delivery_key=planned.delivery_key,
            content=planned.text,
            sender_type=planned.sender_type,
            answer_status=planned.answer_status,
            model_name=planned.model_name,
            prompt_tokens=planned.prompt_tokens,
            completion_tokens=planned.completion_tokens,
            latency_ms=planned.latency_ms,
            source_chunk_ids=planned.source_chunk_ids,
        )
        await session.commit()  # 'sending' 必须先于网络调用持久化

        if state == "sent" or state == "skip":
            continue
        if state == "sending":
            # 上次投递结果不明：宁可漏发可人工补，不可重复轰炸用户（§6）
            assert message_id is not None
            await repositories.mark_outbound(session, message_id, "uncertain")
            await session.commit()
            await sender.notify_operator(
                f"投递结果不明（update {update_id}，key {planned.delivery_key}），请人工确认"
            )
            continue

        assert message_id is not None
        try:
            tg_message_id = await sender.send_message(conversation.telegram_chat_id, planned.text)
        except Exception:
            await repositories.mark_outbound(session, message_id, "failed")
            await session.commit()
            raise
        await repositories.mark_outbound(session, message_id, "sent", tg_message_id)
        await session.commit()


async def run_process_update(
    session_factory: SessionFactory,
    locker: ConversationLocker,
    sender: MessageSender,
    brain: Brain | None,
    update_id: int,
    reply_deadline_s: float = 5.0,
) -> PipelineOutcome:
    """process_update 管线（§6）。arq 任务是它的薄包装。"""
    async with session_factory() as session:
        payload = await repositories.claim_update(session, update_id)
        await session.commit()
    if payload is None:
        return "duplicate"

    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    tg_user = message.get("from")
    chat_id = chat.get("id")
    if chat_id is None or tg_user is None:
        # 非消息类 update（edited_message/callback 等）：MVP 直接跳过
        async with session_factory() as session:
            await repositories.mark_update(session, update_id, "skipped")
            await session.commit()
        return "done"

    async with locker.hold(chat_id) as acquired:
        if not acquired:
            async with session_factory() as session:
                await repositories.requeue_update(session, update_id)
                await session.commit()
            return "locked"
        try:
            async with session_factory() as session:
                user = await repositories.upsert_user(session, tg_user)
                conversation = await repositories.get_or_create_open_conversation(
                    session, chat_id, user.id
                )
                text_content = message.get("text")
                if text_content is not None and message.get("message_id") is not None:
                    await repositories.save_inbound_message(
                        session,
                        conversation_id=conversation.id,
                        update_id=update_id,
                        telegram_message_id=message["message_id"],
                        content=text_content,
                    )
                await session.commit()

                command: str | None = None
                if text_content is None:
                    plan = ReplyPlan(
                        messages=[
                            PlannedMessage(
                                delivery_key=f"reply:{update_id}",
                                text=texts.NON_TEXT_UNSUPPORTED,
                                sender_type="system",
                            )
                        ],
                        final_status="skipped",
                    )
                else:
                    stripped = text_content.strip()
                    command = stripped.split()[0] if stripped.startswith("/") else None
                    routed = _route_command(command, update_id, conversation) if command else None
                    if routed is not None:
                        plan = routed
                    else:
                        plan = await _decide(
                            session,
                            brain,
                            conversation,
                            update_id,
                            text_content,
                            reply_deadline_s,
                        )

                if command == "/reset":
                    await repositories.close_conversation(session, conversation.id)
                    conversation = await repositories.get_or_create_open_conversation(
                        session, chat_id, user.id
                    )
                    await session.commit()

                await _deliver(session, sender, conversation, update_id, plan)

                if plan.notify_operator:
                    await sender.notify_operator(plan.notify_operator)

                await repositories.mark_update(session, update_id, plan.final_status)
                await session.commit()
            return "done"
        except Exception as exc:
            logger.exception("process_update_failed", update_id=update_id)
            async with session_factory() as session:
                await repositories.mark_update(session, update_id, "failed", error=repr(exc))
                await session.commit()
                # 安全兜底文案：自身也走统一投递幂等（§6 第 6 步）
                try:
                    conv = await repositories.get_open_conversation(
                        session,
                        chat_id,
                        (await repositories.upsert_user(session, tg_user)).id,
                    )
                    if conv is not None:
                        await _deliver(
                            session,
                            sender,
                            conv,
                            update_id,
                            ReplyPlan(
                                messages=[
                                    PlannedMessage(
                                        delivery_key=f"fallback:{update_id}",
                                        text=texts.FALLBACK_ERROR,
                                        sender_type="system",
                                    )
                                ]
                            ),
                        )
                except Exception:
                    logger.exception("fallback_delivery_failed", update_id=update_id)
            try:
                await sender.notify_operator(f"消息处理失败（update {update_id}）：{exc!r}")
            except Exception:
                logger.exception("operator_notify_failed", update_id=update_id)
            return "failed"
