"""编排管线业务核心（技术方案 §6）：路由只产出 ReplyPlan，统一投递是唯一发送出口。

依赖以 Protocol 结构化注入（MessageSender / ConversationLocker / Brain），
domain 不 import aiogram/arq/redis/openai 实现。
"""

from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain import handoff, lead_merge, repositories, scoring, texts
from domain.models import Conversation, Message, TelegramUpdate
from domain.schemas import (
    Deadline,
    LeadExtraction,
    PlannedMessage,
    RagAnswer,
    ReplyPlan,
    TriageResult,
)

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


class LeadExtractor(Protocol):
    """llm.extraction.LlmLeadExtractor 实现；测试用 FakeExtractor。"""

    async def extract(
        self,
        history: list[dict[str, str]],
        current_lead: dict[str, object],
        declined_fields: list[str],
    ) -> LeadExtraction: ...


SessionFactory = async_sessionmaker[AsyncSession]

PipelineOutcome = Literal["done", "replied", "locked", "duplicate", "failed"]

ExtractOutcome = Literal["done", "locked", "skipped"]


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
    return None


async def _handle_human_command(
    session: AsyncSession, conversation: Conversation, update_id: int
) -> ReplyPlan:
    """/human 幂等接管（§9）：已在 pending/active 只回确认，不重复 transition、不新建记录。"""
    if conversation.status in handoff.SILENT_STATUSES:
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.HUMAN_ALREADY,
                    sender_type="system",
                )
            ]
        )
    await handoff.transition(session, conversation, "request_human", reason="user_request")
    await session.commit()
    return ReplyPlan(
        messages=[
            PlannedMessage(
                delivery_key=f"reply:{update_id}", text=texts.HUMAN_ACK, sender_type="system"
            )
        ],
        notify_operator=f"用户请求人工（会话 {conversation.id}）",
    )


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

    # §6 第 5 步：购买意图或已有 lead → 回复后由 extract_lead 任务提取（敏感分支除外）
    existing_lead = await repositories.get_lead_by_conversation(session, conversation.id)
    needs_extraction = tri.purchase_intent or existing_lead is not None

    if tri.risk != "none":
        # 静默型触发（§9）：进入 handoff_pending，本条模板是"一次确认"，后续消息只转通知
        await handoff.transition(session, conversation, "request_human", reason="sensitive")
        await session.commit()
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
            ],
            needs_lead_extraction=needs_extraction,
        )

    try:
        ans = await brain.answer(session, text_content, history, tri.language, deadline)
    except Exception:
        logger.warning("rag_answer_failed_refusing", update_id=update_id)
        ans = RagAnswer(refused=True)

    if ans.refused or not ans.text:
        # 通知型触发（§9）：写记录 + 提醒，会话保持 ai_active
        await handoff.notify_only(session, conversation.id, "low_confidence")
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
            needs_lead_extraction=needs_extraction,
        )

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
        ],
        needs_lead_extraction=needs_extraction,
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

                in_human_hands = conversation.status in handoff.SILENT_STATUSES
                command: str | None = None
                if text_content is None:
                    if in_human_hands:
                        # 人工接管中：图片等非文本直接转人工，不发"仅支持文字"打扰
                        plan = ReplyPlan(
                            final_status="skipped",
                            notify_operator=(
                                f"人工接管中，用户发来非文本消息（会话 {conversation.id}）"
                            ),
                        )
                    else:
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
                    if command == "/human":
                        plan = await _handle_human_command(session, conversation, update_id)
                    else:
                        routed = (
                            _route_command(command, update_id, conversation) if command else None
                        )
                        if routed is not None:
                            plan = routed
                        elif in_human_hands:
                            # §6 第 3b 步 / §9：静默态下 AI 不回复，仅转通知——
                            # 这是验收要求 100% 正确的路径
                            plan = ReplyPlan(
                                notify_operator=(
                                    f"人工接管中，用户有新消息（会话 {conversation.id}）："
                                    f"{text_content[:80]}"
                                )
                            )
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

                if plan.final_status == "done" and plan.needs_lead_extraction:
                    # §6 第 5 步：回复已送达，线索提取交给独立任务
                    await repositories.mark_update(session, update_id, "replied")
                    await session.commit()
                    return "replied"
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


async def run_extract_lead(
    session_factory: SessionFactory,
    locker: ConversationLocker,
    sender: MessageSender,
    extractor: LeadExtractor | None,
    update_id: int,
) -> ExtractOutcome:
    """extract_lead 任务（§6）：回复已送达后执行，失败绝不打扰用户。

    提取 → 合并 → 评分 → 追问（单独一条消息）→ 高意向通知 → 实质变更建同步任务；
    成功或最终失败均把 update 收敛到 done，绝不重跑 triage/RAG、绝不发"系统繁忙"。
    """
    async with session_factory() as session:
        row = await session.get(TelegramUpdate, update_id)
        if row is None or row.status != "replied":
            return "skipped"
        payload = row.payload

    message = payload.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    tg_user = message.get("from")
    if chat_id is None or tg_user is None:
        async with session_factory() as session:
            await repositories.mark_update(session, update_id, "done")
            await session.commit()
        return "done"

    async with locker.hold(chat_id) as acquired:
        if not acquired:
            return "locked"  # 状态保持 replied，由重入队/扫描器再试

        async with session_factory() as session:
            try:
                user = await repositories.upsert_user(session, tg_user)
                conversation = await repositories.get_open_conversation(session, chat_id, user.id)
                if conversation is None:  # 会话已被 /reset 关闭等
                    await repositories.mark_update(session, update_id, "done")
                    await session.commit()
                    return "done"

                lead = await repositories.get_or_create_lead(session, user.id, conversation.id)
                await session.commit()
                current = repositories.lead_to_dict(lead)
                old_grade = lead.grade

                if extractor is None:
                    raise RuntimeError("extractor 未配置（缺少 LLM_CHAT_MODEL/LLM_API_KEY）")
                recent = await repositories.get_recent_messages(session, conversation.id)
                history = _history_from_messages(recent)
                extraction = await extractor.extract(history, current, list(lead.declined_fields))

                merge = lead_merge.merge_lead(current, extraction)
                merged = {**current, **merge.updates}
                declined_all = [*lead.declined_fields, *merge.declined_added]
                result = scoring.score_lead(merged)

                values: dict[str, object] = dict(merge.updates)
                if merge.declined_added:
                    values["declined_fields"] = declined_all
                score_changed = result.score != lead.score or result.grade != lead.grade
                if score_changed:
                    values.update(
                        score=result.score, grade=result.grade, score_reasons=result.reasons
                    )
                substantial_change = merge.changed or score_changed
                # 只计算一次：ORM UPDATE 会同步内存对象，事后再读 lead.version 已是新值
                new_version = lead.version + 1
                if substantial_change:
                    values["version"] = new_version
                    await repositories.update_lead(session, lead.id, values)
                    for entry in merge.audit:
                        await repositories.add_audit(
                            session, "ai", "lead_field_update", "lead", lead.id, entry
                        )
                    await session.commit()

                # 追问：仍有缺失关键字段且未被拒绝，且 LLM 给出了问题（§6 第 2 步）
                if extraction.follow_up_question and lead_merge.missing_key_fields(
                    merged, declined_all
                ):
                    await _deliver(
                        session,
                        sender,
                        conversation,
                        update_id,
                        ReplyPlan(
                            messages=[
                                PlannedMessage(
                                    delivery_key=f"followup:{update_id}",
                                    text=extraction.follow_up_question,
                                )
                            ]
                        ),
                    )

                if result.grade == "high" and old_grade != "high":
                    # 通知型触发（§9）：写记录不改状态
                    await handoff.notify_only(session, conversation.id, "high_intent")
                    await session.commit()
                    await sender.notify_operator(
                        f"🔥 高意向线索（会话 {conversation.id}）：score={result.score}，"
                        f"理由 {', '.join(result.reasons)}"
                    )

                if substantial_change:
                    await repositories.create_integration_job(
                        session,
                        integration_type="google_sheets",
                        entity_type="lead",
                        entity_id=lead.id,
                        idempotency_key=f"sheets:lead:{lead.id}:v{new_version}",
                        payload={**merged, "score": result.score, "grade": result.grade},
                    )
                    await session.commit()
                    # TODO(M7): enqueue sync_lead(job)——worker 注册 sync_lead 后开启

                await repositories.mark_update(session, update_id, "done")
                await session.commit()
                return "done"
            except Exception as exc:
                logger.exception("extract_lead_failed", update_id=update_id)
                await session.rollback()
                await repositories.mark_update(
                    session, update_id, "done", error=f"extract_failed: {exc!r}"
                )
                await session.commit()
                try:
                    await sender.notify_operator(
                        f"线索提取失败（update {update_id}），请人工查看会话：{exc!r}"
                    )
                except Exception:
                    logger.exception("operator_notify_failed", update_id=update_id)
                return "done"
