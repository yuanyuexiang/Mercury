"""§11 sync_lead：读最新数据、幂等 upsert、退避重试不丢数据、最终失败通知、扫描器④恢复。"""

from datetime import UTC, datetime, timedelta

from domain import repositories
from domain.models import IntegrationJob, Lead
from domain.orchestrator import run_extract_lead, run_process_update, run_sync_lead
from domain.schemas import LeadExtraction, TriageResult
from sqlalchemy import select, update

from tests.conftest import tg_update

EXTRACTION = LeadExtraction(
    company="Acme Corp",
    business_email="cto@acme-corp.com",
    requirement="Telegram 客服机器人",
    team_size="50 人",
    budget_range="1-2 万美元",
    purchase_timeline="下周",
    asked_demo_or_quote=True,
)


async def _make_job(session_factory, locker, sender, brain, extractor, uid: int = 601) -> int:
    """走真实管线（消息→replied→extract）产出一个 pending 同步任务，返回 job_id。"""
    brain.triage_result = TriageResult(risk="none", purchase_intent=True, needs_rag=True)
    extractor.result = EXTRACTION
    async with session_factory() as session:
        await repositories.insert_update(session, uid, tg_update(uid, "50人团队要报价"))
        await session.commit()
    assert await run_process_update(session_factory, locker, sender, brain, uid) == "replied"
    outcome, job_id = await run_extract_lead(session_factory, locker, sender, extractor, uid)
    assert outcome == "done" and job_id is not None
    return job_id


async def test_sync_happy_path(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    """成功同步：job done + completed_at，lead 回填 external_crm_id/status，行内容取最新数据。"""
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "done"

    async with session_factory() as session:
        job = (await session.execute(select(IntegrationJob))).scalar_one()
        assert job.status == "done" and job.completed_at is not None
        lead = (await session.execute(select(Lead))).scalar_one()
        assert lead.external_crm_id == f"row:{lead.id + 1}" and lead.status == "synced"

    row = sync_port.rows[1]
    assert row["company"] == "Acme Corp" and row["grade"] == "high" and row["score"] == 110
    assert row["summary"] == summarizer.text
    assert row["telegram"] == "@tester" and row["synced_at"]


async def test_retry_backoff_no_data_loss(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    """M7 验收：断网重试后数据无丢失——失败两次退避重试，第三次成功，行数据完整。"""
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    sync_port.fail_times = 2

    outcome, delay = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "retry" and delay == 2 * 60  # 2^1 分钟
    async with session_factory() as session:
        job = (await session.execute(select(IntegrationJob))).scalar_one()
        assert job.status == "pending" and job.attempts == 1
        assert job.next_retry_at is not None and job.last_error

    outcome, delay = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "retry" and delay == 4 * 60  # 2^2 分钟

    outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "done"
    async with session_factory() as session:
        lead = (await session.execute(select(Lead))).scalar_one()
        assert lead.company == "Acme Corp", "原始 lead 数据不因同步失败丢失"
    assert sync_port.rows[1]["company"] == "Acme Corp"


async def test_final_failure_notifies(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    """attempts ≥ 5 → failed + 通知运营者，lead 数据完好。"""
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    sync_port.fail_times = 99
    for _ in range(4):
        outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
        assert outcome == "retry"
    outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "failed"
    assert any("最终失败" in n for n in sender.notices)
    async with session_factory() as session:
        job = (await session.execute(select(IntegrationJob))).scalar_one()
        assert job.status == "failed" and job.attempts == 5


async def test_idempotent_upsert_across_versions(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    """M7 验收：Sheet 行幂等更新——lead 二次变更产生新任务，仍是同一行、内容为最新。"""
    job_id = await _make_job(session_factory, locker, sender, brain, extractor, uid=611)
    await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)

    # 第二轮：用户补充信息 → 新版本新任务
    extractor.result = LeadExtraction(company="Acme Corp（新加坡）")
    async with session_factory() as session:
        await repositories.insert_update(session, 612, tg_update(612, "我们是新加坡分部"))
        await session.commit()
    await run_process_update(session_factory, locker, sender, brain, 612)
    outcome, job_id2 = await run_extract_lead(session_factory, locker, sender, extractor, 612)
    assert job_id2 is not None and job_id2 != job_id
    await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id2)

    assert len(sync_port.rows) == 1, "同一 lead 永远一行"
    assert sync_port.rows[1]["company"] == "Acme Corp（新加坡）"
    async with session_factory() as session:
        jobs = (await session.execute(select(IntegrationJob))).scalars().all()
        assert sorted(j.status for j in jobs) == ["done", "done"]


async def test_summary_failure_does_not_block_sync(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    summarizer.raise_error = True
    outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "done"
    assert sync_port.rows[1]["summary"] == ""


async def test_claim_prevents_double_sync(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    """done 后再跑同一 job → skipped，不重复写表。"""
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "skipped"
    assert sync_port.calls == 1


async def test_unconfigured_port_fails_with_notice(
    session_factory, locker, sender, brain, extractor, summarizer
) -> None:
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    outcome, delay = await run_sync_lead(session_factory, None, summarizer, sender, job_id)
    assert outcome == "retry" and delay is not None  # 配好凭据后重试即可恢复
    async with session_factory() as session:
        job = (await session.execute(select(IntegrationJob))).scalar_one()
        assert "未配置" in (job.last_error or "")


async def test_sweeper_recovers_stuck_running_job(
    session_factory, locker, sender, brain, extractor, sync_port, summarizer
) -> None:
    """扫描器④：running 超时原子重置为 pending，可被再次抢占完成。"""
    job_id = await _make_job(session_factory, locker, sender, brain, extractor)
    async with session_factory() as session:
        await session.execute(
            update(IntegrationJob)
            .where(IntegrationJob.id == job_id)
            .values(status="running", picked_at=datetime.now(UTC) - timedelta(minutes=30))
        )
        await session.commit()

    async with session_factory() as session:
        reset_ids = await repositories.reset_expired_running_jobs(session, lease_minutes=10)
        await session.commit()
    assert reset_ids == [job_id]

    outcome, _ = await run_sync_lead(session_factory, sync_port, summarizer, sender, job_id)
    assert outcome == "done"
