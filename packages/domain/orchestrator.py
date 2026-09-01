"""编排管线业务核心（技术方案 §6）：路由只产出 ReplyPlan，统一投递是唯一发送出口。

依赖以 Protocol 结构化注入（MessageSender / ConversationLocker / Brain），
domain 不 import aiogram/arq/redis/openai 实现。
"""

import re
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Literal, Protocol

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain import handoff, lead_merge, repositories, scoring, texts
from domain.models import Conversation, Lead, Message, User
from domain.schemas import (
    Deadline,
    LeadExtraction,
    LlmNotConfiguredError,
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


class LeadSync(Protocol):
    """integrations.sheets.GoogleSheetsLeadSync 实现；测试用 FakeSyncPort（§11）。"""

    async def upsert_lead(self, row: dict[str, object]) -> str: ...


class Summarizer(Protocol):
    """llm.brain.ConversationSummarizer 实现（§11 摘要列）。"""

    async def summarize(self, history: list[dict[str, str]]) -> str: ...


SessionFactory = async_sessionmaker[AsyncSession]

PipelineOutcome = Literal["done", "replied", "locked", "duplicate", "failed"]

ExtractOutcome = Literal["done", "locked", "skipped"]

SyncOutcome = Literal["done", "retry", "failed", "skipped"]

SYNC_MAX_ATTEMPTS = 5


def _history_from_messages(messages: list[Message]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for m in messages:
        role = "user" if m.direction == "inbound" else "assistant"
        history.append({"role": role, "content": m.content})
    return history


_CHANNEL_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


async def _capture_start_channel(
    session: AsyncSession, conversation: Conversation, stripped_text: str
) -> None:
    """渠道归因：/start <payload> 深链参数（t.me/<bot>?start=xxx）。

    首触归因——已有渠道不覆盖；payload 是用户可控数据，仅接受 Telegram
    深链合法字符集（字母数字_-，≤64），其余静默丢弃。
    """
    parts = stripped_text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if not payload or conversation.source_channel is not None:
        return
    if not _CHANNEL_RE.fullmatch(payload):
        return
    conversation.source_channel = payload
    await session.commit()


def _route_command(
    command: str,
    update_id: int,
    conversation: Conversation,
    brand_name: str = "",
    lang: str = "",
) -> ReplyPlan | None:
    """命令分支（不经 LLM，§6 第 3a 步）。返回 None 表示不是已知命令。"""
    if command == "/start":
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.welcome(brand_name, lang),
                    sender_type="system",
                )
            ]
        )
    if command == "/reset":
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.reset_done(lang),
                    sender_type="system",
                )
            ]
        )
    return None


async def _handle_human_command(
    session: AsyncSession, conversation: Conversation, update_id: int, lang: str = ""
) -> ReplyPlan:
    """/human 幂等接管（§9）：已在 pending/active 只回确认，不重复 transition、不新建记录。"""
    if conversation.status in handoff.SILENT_STATUSES:
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.human_already(lang),
                    sender_type="system",
                )
            ]
        )
    await handoff.transition(session, conversation, "request_human", reason="user_request")
    await session.commit()
    return ReplyPlan(
        messages=[
            PlannedMessage(
                delivery_key=f"reply:{update_id}", text=texts.human_ack(lang), sender_type="system"
            )
        ],
        notify_operator=f"用户请求人工（会话 {conversation.id}）",
    )


def _not_configured_plan(conversation: Conversation, update_id: int, lang: str = "") -> ReplyPlan:
    return ReplyPlan(
        messages=[
            PlannedMessage(
                delivery_key=f"reply:{update_id}",
                text=texts.llm_not_configured(lang),
                sender_type="system",
                answer_status="refused",
            )
        ],
        notify_operator=f"LLM 未配置，会话 {conversation.id} 无法回复（后台「模型配置」可激活）",
    )


async def _decide(
    session: AsyncSession,
    brain: Brain | None,
    conversation: Conversation,
    update_id: int,
    text_content: str,
    reply_deadline_s: float,
    user_lang: str = "",
) -> ReplyPlan:
    """非命令文本的路由（§6 第 3c–3e 步）：triage → RAG/闲聊，全程共享端到端 deadline。"""
    if brain is None:
        return _not_configured_plan(conversation, update_id, user_lang)

    deadline = Deadline(reply_deadline_s)
    recent = await repositories.get_recent_messages(session, conversation.id)
    history = _history_from_messages(recent)

    try:
        tri = await brain.triage(history, deadline)
    except LlmNotConfiguredError:
        return _not_configured_plan(conversation, update_id, user_lang)
    except Exception:
        logger.warning("triage_failed_using_defaults", update_id=update_id)
        tri = TriageResult()  # risk=none, needs_rag=True：宁可多检索，不可漏风险以外的回答

    # §6 第 5 步：购买意图或已有 lead → 回复后由 extract_lead 任务提取（敏感分支除外）
    # 客户语言：triage 识别优先（跟随消息语言），未识别时用 Telegram 档案语言
    lang = tri.language if tri.language not in ("", "auto") else user_lang

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
                    text=texts.sensitive_to_human(lang),
                    sender_type="system",
                    answer_status="handoff",
                )
            ],
            notify_operator=f"敏感问题（{tri.risk}）需人工接管，会话 {conversation.id}",
        )

    if not tri.needs_rag:
        if tri.purchase_intent:
            # 纯购买表态（triage 认为无需检索）：绝不能回问候语——
            # 确认接单，信息收集交给 extract_lead 的追问（§6 第 5 步）
            return ReplyPlan(
                messages=[
                    PlannedMessage(
                        delivery_key=f"reply:{update_id}",
                        text=texts.purchase_ack(lang),
                        sender_type="system",
                    )
                ],
                notify_operator=(
                    f"客户表达购买意向（会话 {conversation.id}）：{text_content[:80]}"
                ),
                needs_lead_extraction=True,
            )
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.smalltalk(lang),
                    sender_type="system",
                )
            ],
            needs_lead_extraction=needs_extraction,
        )

    try:
        ans = await brain.answer(session, text_content, history, tri.language, deadline)
    except LlmNotConfiguredError:
        return _not_configured_plan(conversation, update_id, user_lang)
    except Exception:
        logger.warning("rag_answer_failed_refusing", update_id=update_id)
        ans = RagAnswer(refused=True)

    if ans.refused or not ans.text:
        if tri.purchase_intent:
            # 购买意向的表态（"我想要 X"）不是知识问答：RAG 没东西可"回答"很正常，
            # 但绝不能给客户"答不上来"的观感——确认 + 引导补充信息，
            # 后续由 extract_lead 完成追问/评分/高意向通知（§6 第 5 步）
            return ReplyPlan(
                messages=[
                    PlannedMessage(
                        delivery_key=f"reply:{update_id}",
                        text=texts.purchase_ack(lang),
                        sender_type="system",
                    )
                ],
                notify_operator=(
                    f"客户表达购买意向（会话 {conversation.id}）：{text_content[:80]}"
                ),
                needs_lead_extraction=True,
            )
        # 通知型触发（§9）：写记录 + 提醒，会话保持 ai_active
        await handoff.notify_only(session, conversation.id, "low_confidence")
        return ReplyPlan(
            messages=[
                PlannedMessage(
                    delivery_key=f"reply:{update_id}",
                    text=texts.refused_no_answer(lang),
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
    brand_name: str = "",
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
    user_lang = (tg_user or {}).get("language_code") or ""
    chat_id = chat.get("id")
    if chat_id is None or tg_user is None:
        # 非消息类 update（edited_message/callback 等）：MVP 直接跳过
        async with session_factory() as session:
            await repositories.mark_update(session, update_id, "skipped")
            await session.commit()
        return "done"

    async with session_factory() as session:
        # 顺序守卫（第三轮评审）：同 chat 有更早未完成 update（如扫描器恢复的旧消息）
        # → 让位重试，避免旧消息在 /reset 之后乱序进入新会话
        if await repositories.has_earlier_pending_update(session, chat_id, update_id):
            await repositories.requeue_update(session, update_id)
            await session.commit()
            return "locked"

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
                                    text=texts.non_text_unsupported(user_lang),
                                    sender_type="system",
                                )
                            ],
                            final_status="skipped",
                        )
                else:
                    stripped = text_content.strip()
                    command = stripped.split()[0] if stripped.startswith("/") else None
                    if command == "/start":
                        await _capture_start_channel(session, conversation, stripped)
                    if command == "/human":
                        plan = await _handle_human_command(
                            session, conversation, update_id, user_lang
                        )
                    else:
                        routed = (
                            _route_command(command, update_id, conversation, brand_name, user_lang)
                            if command
                            else None
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
                                user_lang,
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
                                        text=texts.fallback_error(user_lang),
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
) -> tuple[ExtractOutcome, int | None]:
    """extract_lead 任务（§6）：回复已送达后执行，失败绝不打扰用户。

    提取 → 合并 → 评分 → 追问（单独一条消息）→ 高意向通知 → 实质变更建同步任务；
    成功或最终失败均把 update 收敛到 done，绝不重跑 triage/RAG、绝不发"系统繁忙"。
    返回 (outcome, 新建同步任务的 job_id)；job_id 非 None 时由 wrapper 入队 sync_lead。
    """
    async with session_factory() as session:
        # 原子抢占（第三轮评审）：replied → extracting，并发重复入队只有一个能通过
        payload = await repositories.claim_replied_update(session, update_id)
        await session.commit()
    if payload is None:
        return "skipped", None

    message = payload.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    tg_user = message.get("from")
    if chat_id is None or tg_user is None:
        async with session_factory() as session:
            await repositories.mark_update(session, update_id, "done")
            await session.commit()
        return "done", None

    async with locker.hold(chat_id) as acquired:
        if not acquired:
            async with session_factory() as session:
                await repositories.mark_update(session, update_id, "replied")  # 让位，回到可抢占态
                await session.commit()
            return "locked", None

        async with session_factory() as session:
            try:
                user = await repositories.upsert_user(session, tg_user)
                conversation = await repositories.get_open_conversation(session, chat_id, user.id)
                if conversation is None:  # 会话已被 /reset 关闭等
                    await repositories.mark_update(session, update_id, "done")
                    await session.commit()
                    return "done", None

                lead = await repositories.get_or_create_lead(
                    session, user.id, conversation.id, conversation.source_channel
                )
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

                job_id: int | None = None
                if substantial_change:
                    job_id = await repositories.create_integration_job(
                        session,
                        integration_type="google_sheets",
                        entity_type="lead",
                        entity_id=lead.id,
                        idempotency_key=f"sheets:lead:{lead.id}:v{new_version}",
                        payload={**merged, "score": result.score, "grade": result.grade},
                    )
                    await session.commit()

                await repositories.mark_update(session, update_id, "done")
                await session.commit()
                return "done", job_id
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
                return "done", None


def _build_sync_row(
    lead: Lead, user: User, conversation: Conversation, summary: str
) -> dict[str, object]:
    """§11：任务执行时从 DB 读 lead 当前状态组装（payload 仅作审计快照），乱序执行无害。"""
    telegram = f"@{user.username}" if user.username else str(user.telegram_user_id)
    last_contact = (
        conversation.last_message_at.isoformat(timespec="seconds")
        if conversation.last_message_at
        else ""
    )
    return {
        "lead_id": lead.id,
        "telegram": telegram,
        "name": lead.name,
        "company": lead.company,
        "country": lead.country,
        "business_email": lead.business_email,
        "requirement": lead.requirement,
        "team_size": lead.team_size,
        "budget_range": lead.budget_range,
        "purchase_timeline": lead.purchase_timeline,
        "integrations": ", ".join(lead.integrations or []),
        "notes": lead.notes,
        "score": lead.score,
        "grade": lead.grade,
        "summary": summary,
        "last_contact": last_contact,
        "synced_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_channel": lead.source_channel,
    }


async def run_sync_lead(
    session_factory: SessionFactory,
    sync_port: LeadSync | None,
    summarizer: Summarizer | None,
    sender: MessageSender,
    job_id: int,
) -> tuple[SyncOutcome, int | None]:
    """sync_lead 任务（§11）：原子抢占 → 读最新 lead → 摘要 → upsert → 完成/退避重试。

    返回 (outcome, retry_delay_seconds)；outcome=="retry" 时由 wrapper 按 delay 重入队。
    失败退避 2^attempts 分钟，attempts ≥ SYNC_MAX_ATTEMPTS 置 failed 并通知运营者；
    原始 lead 数据永不因同步失败而丢失。
    """
    async with session_factory() as session:
        job = await repositories.claim_integration_job(session, job_id)
        await session.commit()
    if job is None:
        return "skipped", None  # 已完成/进行中/已失败

    try:
        async with session_factory() as session:
            lead = await repositories.get_lead(session, job.entity_id)
            if lead is None:
                await repositories.complete_integration_job(session, job.id)
                await session.commit()
                logger.warning("sync_lead_missing_lead", job_id=job.id, lead_id=job.entity_id)
                return "done", None
            user = await session.get(User, lead.user_id)
            conversation = await session.get(Conversation, lead.conversation_id)
            assert user is not None and conversation is not None

            summary = ""
            if summarizer is not None:
                try:
                    history = _history_from_messages(
                        await repositories.get_recent_messages(
                            session, lead.conversation_id, limit=20
                        )
                    )
                    summary = await summarizer.summarize(history)
                except Exception:
                    logger.warning("summary_failed_continuing", job_id=job.id)

            row = _build_sync_row(lead, user, conversation, summary)

        if sync_port is None:
            raise RuntimeError(
                "google_sheets 未配置（GOOGLE_SERVICE_ACCOUNT_JSON / LEADS_SPREADSHEET_ID）"
            )
        external_id = await sync_port.upsert_lead(row)

        async with session_factory() as session:
            await repositories.complete_integration_job(session, job.id)
            await repositories.update_lead(
                session, lead.id, {"external_crm_id": external_id, "status": "synced"}
            )
            await session.commit()
        logger.info("sync_lead_done", job_id=job.id, lead_id=lead.id, external_id=external_id)
        return "done", None

    except Exception as exc:
        attempts = job.attempts + 1
        logger.warning("sync_lead_failed", job_id=job.id, attempts=attempts, error=repr(exc))
        async with session_factory() as session:
            if attempts >= SYNC_MAX_ATTEMPTS:
                await repositories.fail_integration_job(session, job.id, attempts, repr(exc))
                await session.commit()
                try:
                    await sender.notify_operator(
                        f"⚠️ CRM 同步最终失败（job {job.id}，lead {job.entity_id}）："
                        f"{exc!r}。后台可手动重试。"
                    )
                except Exception:
                    logger.exception("operator_notify_failed", job_id=job.id)
                return "failed", None
            delay_seconds = (2**attempts) * 60
            await repositories.retry_integration_job(
                session, job.id, attempts, repr(exc), delay_seconds
            )
            await session.commit()
            return "retry", delay_seconds


async def run_revive_leads(
    session_factory: SessionFactory,
    sender: MessageSender,
    *,
    after_days: int = 3,
    max_attempts: int = 1,
    brand_name: str = "",
) -> int:
    """沉睡线索唤醒（每日 cron）：对聊过但安静了 N 天的中高意向线索发一条跟进。

    克制原则：只打扰 ai_active 会话（human_active/closed 绝不碰，§9 状态机约束）、
    只看 open 的 medium/high 线索、每条线索至多 max_attempts 次（revive_count 持久防重）。
    文案是确定性模板（texts.revive_follow_up），不走 LLM——绝不编造承诺。
    逐条独立事务：单条失败只记日志，不影响其余。返回实际发送数。
    """
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=after_days)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Lead, Conversation)
                .join(Conversation, Lead.conversation_id == Conversation.id)
                .where(
                    Lead.status == "open",
                    Lead.grade.in_(["medium", "high"]),
                    Lead.revive_count < max_attempts,
                    Conversation.status == "ai_active",
                    Conversation.last_message_at.is_not(None),
                    Conversation.last_message_at < cutoff,
                )
            )
        ).all()

    sent = 0
    text = texts.revive_follow_up(brand_name)
    for lead, conversation in rows:
        try:
            tg_message_id = await sender.send_message(conversation.telegram_chat_id, text)
        except Exception:
            logger.warning("revive_send_failed", lead_id=lead.id)
            continue
        async with session_factory() as session:
            session.add(
                Message(
                    conversation_id=conversation.id,
                    telegram_message_id=tg_message_id,
                    direction="outbound",
                    sender_type="system",
                    content=text,
                    delivery_status="sent",
                )
            )
            await repositories.update_lead(
                session,
                lead.id,
                {"revive_count": lead.revive_count + 1, "last_revived_at": func.now()},
            )
            await repositories.touch_last_message(session, conversation.id)
            await repositories.add_audit(
                session,
                "system",
                "lead_revived",
                "lead",
                lead.id,
                {"attempt": lead.revive_count + 1},
            )
            await session.commit()
        sent += 1
        logger.info("lead_revived", lead_id=lead.id, conversation_id=conversation.id)
    return sent
