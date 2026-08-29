"""§6 extract_lead 任务：提取→合并→评分→追问→高意向通知→版本化同步任务；失败不打扰用户。"""

from domain import repositories
from domain.models import IntegrationJob, Lead, Message, TelegramUpdate
from domain.orchestrator import run_extract_lead, run_process_update
from domain.schemas import LeadExtraction, TriageResult
from sqlalchemy import select

from tests.conftest import tg_update


async def _seed_replied(session_factory, locker, sender, brain, uid: int, text: str) -> None:
    """走真实管线到 'replied'：purchase_intent=True → 回复送达 + 入队点。"""
    brain.triage_result = TriageResult(risk="none", purchase_intent=True, needs_rag=True)
    async with session_factory() as session:
        await repositories.insert_update(session, uid, tg_update(uid, text))
        await session.commit()
    outcome = await run_process_update(session_factory, locker, sender, brain, uid)
    assert outcome == "replied"


HIGH_INTENT_EXTRACTION = LeadExtraction(
    company="Acme Corp",
    business_email="cto@acme-corp.com",
    requirement="Telegram 客服机器人",
    team_size="50 人",
    budget_range="1-2 万美元",
    purchase_timeline="下周",
    asked_demo_or_quote=True,
)


async def test_high_intent_flow(session_factory, locker, sender, brain, extractor) -> None:
    """验收：演示剧本后半段——产生 high 线索且理由正确、通知运营者、建版本化同步任务。"""
    await _seed_replied(
        session_factory, locker, sender, brain, 401, "50人团队，下周要上线，帮我报价"
    )
    extractor.result = HIGH_INTENT_EXTRACTION

    outcome, job_id = await run_extract_lead(session_factory, locker, sender, extractor, 401)
    assert outcome == "done" and job_id is not None

    async with session_factory() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
        assert lead.grade == "high" and lead.score == 110
        assert lead.score_reasons == [
            "company_email",
            "clear_need",
            "team_size_fit",
            "budget_given",
            "timeline_30d",
            "asked_demo",
        ]
        assert lead.company == "Acme Corp" and lead.asked_demo is True
        assert lead.version == 2  # 实质变更 +1

        job = (await session.execute(select(IntegrationJob))).scalar_one()
        assert job.idempotency_key == f"sheets:lead:{lead.id}:v2"
        assert job.status == "pending" and job.payload["grade"] == "high"

        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "done"

    assert any("高意向线索" in n for n in sender.notices)


async def test_followup_question_sent(session_factory, locker, sender, brain, extractor) -> None:
    """缺关键字段 → 追问以单独一条消息发送（delivery_key followup:{uid}）。"""
    await _seed_replied(session_factory, locker, sender, brain, 402, "我们想采购")
    extractor.result = LeadExtraction(
        company="Beta Inc", follow_up_question="方便留一个工作邮箱吗？"
    )
    assert (await run_extract_lead(session_factory, locker, sender, extractor, 402))[0] == "done"

    assert sender.sent[-1][1] == "方便留一个工作邮箱吗？"
    async with session_factory() as session:
        followup = (
            await session.execute(select(Message).where(Message.delivery_key == "followup:402"))
        ).scalar_one()
        assert followup.delivery_status == "sent"


async def test_no_followup_when_declined(session_factory, locker, sender, brain, extractor) -> None:
    """验收：用户拒绝后不再追问——关键字段全部填了或被拒 → 即使 LLM 给了问题也不发。"""
    await _seed_replied(session_factory, locker, sender, brain, 403, "预算不方便透露")
    extractor.result = LeadExtraction(
        company="Gamma",
        business_email="a@gamma.io",
        requirement="bot",
        team_size="20",
        purchase_timeline="下周",
        refused_fields=["budget_range"],
        follow_up_question="预算大概多少呢？",  # LLM 违规给了问题，代码层兜底不发
    )
    sent_before = len(sender.sent)
    assert (await run_extract_lead(session_factory, locker, sender, extractor, 403))[0] == "done"
    assert len(sender.sent) == sent_before, "不应有追问消息"
    async with session_factory() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
        assert lead.declined_fields == ["budget_range"]


async def test_extract_failure_never_disturbs_user(
    session_factory, locker, sender, brain, extractor
) -> None:
    """第二轮评审修复项：extraction 失败 → 用户收不到"系统繁忙"，update 仍收敛到 done。"""
    await _seed_replied(session_factory, locker, sender, brain, 404, "想了解一下")
    extractor.raise_error = True
    sent_before = len(sender.sent)

    outcome, job_id = await run_extract_lead(session_factory, locker, sender, extractor, 404)
    assert outcome == "done" and job_id is None
    assert len(sender.sent) == sent_before
    assert any("线索提取失败" in n for n in sender.notices)
    async with session_factory() as session:
        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "done" and "extract_failed" in (row.error or "")


async def test_skip_when_not_replied(session_factory, locker, sender, extractor) -> None:
    """状态不是 replied（已处理过/未回复）→ skipped，不重复提取。"""
    async with session_factory() as session:
        await repositories.insert_update(session, 405, tg_update(405, "hi"))
        await session.commit()
    assert (await run_extract_lead(session_factory, locker, sender, extractor, 405))[0] == "skipped"
    assert extractor.calls == []


async def test_no_change_no_new_job(session_factory, locker, sender, brain, extractor) -> None:
    """第二次提取无实质变更 → 版本不动、不建新同步任务（幂等）。"""
    await _seed_replied(session_factory, locker, sender, brain, 406, "50人团队，帮我报价")
    extractor.result = HIGH_INTENT_EXTRACTION
    await run_extract_lead(session_factory, locker, sender, extractor, 406)

    # 同会话再来一条消息，提取结果与已存内容完全一致
    await _seed_replied(session_factory, locker, sender, brain, 407, "对，就这些")
    outcome, job_id = await run_extract_lead(session_factory, locker, sender, extractor, 407)
    assert outcome == "done" and job_id is None, "无变更不应建新任务"

    async with session_factory() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
        assert lead.version == 2, "无变更不应再 bump"
        jobs = (await session.execute(select(IntegrationJob))).scalars().all()
        assert len(jobs) == 1
