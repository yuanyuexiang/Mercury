"""§10 后台 API：认证/CSRF/限流、会话接管、线索修正重评分、知识库、供应商配置与热切换。"""

from typing import Any

import bcrypt
import httpx
import pytest
from api.main import create_app
from domain import repositories
from domain.config import Settings
from domain.models import IntegrationJob, Lead, LlmProvider
from domain.orchestrator import run_extract_lead, run_process_update
from domain.schemas import LeadExtraction, TriageResult
from llm.provider_config import ProviderSource, decrypt_api_key
from sqlalchemy import select

from tests.conftest import FakeSender, tg_update

PASSWORD = "admin-secret-123"
FERNET_KEY = "5adLfTdIiTupBnc0mkxSFcCLm4V2XdBperNzHbPWY7Y="  # 测试专用


class StubArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((name, args))


class FakeTestChat:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def chat(self, messages: Any, *, purpose: str, timeout_s: float, schema: Any = None):
        if not self.ok:
            raise ConnectionError("bad key")
        return type("R", (), {"content": "pong"})()


@pytest.fixture
def settings(redis_client) -> Settings:
    return Settings(
        admin_username="admin",
        admin_password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode(),
        jwt_secret="test-jwt-secret",
        settings_encryption_key=FERNET_KEY,
        telegram_webhook_secret="hook-secret",
    )


@pytest.fixture
async def client(session_factory, redis_client, settings, sender):
    from integrations.app_settings import AppSettingsStore

    app = create_app()
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.redis = redis_client
    app.state.arq = StubArq()
    app.state.sender = sender
    app.state.chat_client_factory = lambda base_url, api_key, model: FakeTestChat(ok=True)
    app.state.app_settings_store = AppSettingsStore(session_factory, redis_client, settings)

    async def _fake_probe(token: str) -> str:
        return "test_bot"

    async def _fake_register(token: str, base_url: str, secret: str) -> None:
        return None

    app.state.telegram_probe = _fake_probe
    app.state.telegram_register = _fake_register
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        yield http


WRITE_HEADERS = {"X-Requested-With": "fetch"}


async def _login(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": PASSWORD},
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 200


async def test_auth_flow(client) -> None:
    assert (await client.get("/api/conversations")).status_code == 401
    bad = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong"}, headers=WRITE_HEADERS
    )
    assert bad.status_code == 401
    await _login(client)
    assert (await client.get("/api/conversations")).status_code == 200


async def test_login_rate_limit(client) -> None:
    for _ in range(5):
        await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
            headers=WRITE_HEADERS,
        )
    resp = await client.post(
        "/api/auth/login", json={"username": "admin", "password": PASSWORD}, headers=WRITE_HEADERS
    )
    assert resp.status_code == 429


async def test_csrf_required_on_writes(client, session_factory, locker, brain) -> None:
    await _login(client)
    async with session_factory() as session:
        await repositories.insert_update(session, 701, tg_update(701, "hi"))
        await session.commit()
    await run_process_update(session_factory, locker, client.app.state.sender, brain, 701)
    resp = await client.post("/api/conversations/1/handoff")  # 无 CSRF 头
    assert resp.status_code == 403


async def test_takeover_and_resume_and_operator_message(
    client, session_factory, locker, brain, sender: FakeSender
) -> None:
    await _login(client)
    async with session_factory() as session:
        await repositories.insert_update(session, 702, tg_update(702, "你好"))
        await session.commit()
    await run_process_update(session_factory, locker, sender, brain, 702)

    resp = await client.post("/api/conversations/1/handoff", headers=WRITE_HEADERS)
    assert resp.status_code == 200 and resp.json()["status"] == "human_active"

    resp = await client.post(
        "/api/conversations/1/messages", json={"text": "您好，我是人工客服"}, headers=WRITE_HEADERS
    )
    assert resp.status_code == 200
    assert sender.sent[-1] == (1000, "您好，我是人工客服")

    resp = await client.post("/api/conversations/1/resume-ai", headers=WRITE_HEADERS)
    assert resp.status_code == 200 and resp.json()["status"] == "ai_active"

    detail = (await client.get("/api/conversations/1")).json()
    assert detail["conversation"]["status"] == "ai_active"
    assert any(m["sender_type"] == "operator" for m in detail["messages"])
    assert detail["handoffs"], "接管历史应可见"


async def test_lead_patch_rescores_and_syncs(
    client, session_factory, locker, brain, sender, extractor
) -> None:
    await _login(client)
    brain.triage_result = TriageResult(purchase_intent=True)
    extractor.result = LeadExtraction(company="Acme")
    async with session_factory() as session:
        await repositories.insert_update(session, 703, tg_update(703, "想采购"))
        await session.commit()
    await run_process_update(session_factory, locker, sender, brain, 703)
    await run_extract_lead(session_factory, locker, sender, extractor, 703)

    resp = await client.patch(
        "/api/leads/1",
        json={"business_email": "cto@acme.io", "requirement": "客服机器人"},
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 35 and data["grade"] == "medium"  # company_email 15 + clear_need 20
    assert "company_email" in data["score_reasons"]
    assert any(name == "sync_lead" for name, _ in client.app.state.arq.jobs)


async def test_knowledge_upload_and_lifecycle(client, session_factory, tmp_path) -> None:
    await _login(client)
    client.app.state.settings.storage_dir = str(tmp_path)
    resp = await client.post(
        "/api/knowledge/documents",
        files={"file": ("guide.md", b"# Hello\n\ncontent", "text/markdown")},
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]
    assert ("index_document", (doc_id,)) in [(n, a[:1]) for n, a in client.app.state.arq.jobs]

    resp = await client.patch(
        f"/api/knowledge/documents/{doc_id}", json={"status": "disabled"}, headers=WRITE_HEADERS
    )
    assert resp.json()["status"] == "disabled"

    resp = await client.post(
        "/api/knowledge/documents",
        files={"file": ("guide2.md", b"# Hello\n\ncontent", "text/markdown")},
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 409  # checksum 去重

    assert (
        await client.delete(f"/api/knowledge/documents/{doc_id}", headers=WRITE_HEADERS)
    ).status_code == 200


async def test_url_import_ssrf_blocked(client) -> None:
    await _login(client)
    for bad in ("http://127.0.0.1/x", "http://169.254.169.254/meta", "ftp://a.com/x"):
        resp = await client.post(
            "/api/knowledge/documents/url",
            json={"url": bad, "title": "t"},
            headers=WRITE_HEADERS,
        )
        assert resp.status_code == 422, bad


async def test_provider_crud_activate_and_hot_reload(
    client, session_factory, redis_client, settings, monkeypatch
) -> None:
    # mock DNS：开发机若开 fake-ip 代理，所有域名会解析进保留网段被 SSRF 校验误拦
    monkeypatch.setattr(
        "integrations.netguard.socket.getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    await _login(client)
    resp = await client.post(
        "/api/settings/llm-providers",
        json={
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-test-1234abcd",
            "chat_model": "deepseek-chat",
            "embed_model": "text-embedding-3-small",
        },
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 200
    provider = resp.json()
    assert "sk-test" not in str(provider), "明文 key 绝不能出现在响应中"

    async with session_factory() as session:
        row = (await session.execute(select(LlmProvider))).scalar_one()
        assert row.api_key_enc != "sk-test-1234abcd"
        assert decrypt_api_key(settings, row.api_key_enc) == "sk-test-1234abcd"

    resp = await client.post(
        f"/api/settings/llm-providers/{provider['id']}/activate", headers=WRITE_HEADERS
    )
    assert resp.status_code == 200

    # 热切换：ProviderSource 应解析到 DB 供应商（模拟 worker 侧）
    source = ProviderSource(session_factory, redis_client, settings)
    config = await source.get()
    assert config is not None and config.source == "db"
    assert config.chat_model == "deepseek-chat" and config.api_key == "sk-test-1234abcd"
    assert config.embed_model == "text-embedding-3-small"  # 后台可配 embedding（§12 修订）

    # 测试连接（Fake chat 工厂）
    resp = await client.post(
        f"/api/settings/llm-providers/{provider['id']}/test", headers=WRITE_HEADERS
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True

    # 激活中的不可删
    resp = await client.delete(
        f"/api/settings/llm-providers/{provider['id']}", headers=WRITE_HEADERS
    )
    assert resp.status_code == 409


async def test_provider_source_env_fallback_and_invalidate(
    session_factory, redis_client, settings
) -> None:
    source = ProviderSource(session_factory, redis_client, settings)
    assert await source.get() is None  # DB 空且 env 未配 chat 模型

    env_settings = settings.model_copy(update={"llm_api_key": "sk-env", "llm_chat_model": "gpt-x"})
    source2 = ProviderSource(session_factory, redis_client, env_settings)
    config = await source2.get()
    assert config is not None and config.source == "env" and config.chat_model == "gpt-x"

    source2.invalidate()
    assert (await source2.get()) is not None  # 失效后重查仍可用


async def test_metrics_endpoints(client, session_factory, locker, brain, sender) -> None:
    await _login(client)
    brain.refuse = True
    async with session_factory() as session:
        await repositories.insert_update(session, 704, tg_update(704, "冷门问题"))
        await session.commit()
    await run_process_update(session_factory, locker, sender, brain, 704)

    overview = (await client.get("/api/metrics/overview")).json()
    assert overview["messages"] >= 2 and overview["refused"] == 1
    gaps = (await client.get("/api/metrics/knowledge-gaps")).json()
    assert gaps["items"][0]["question"] == "冷门问题"
    assert (await client.get("/api/metrics/costs")).status_code == 200


async def test_user_data_deletion(
    client, session_factory, locker, brain, sender, extractor
) -> None:
    """第三轮评审：DELETE /api/users/by-telegram/{id}——级联删除 + jobs/audit 清理 + 匿名审计。"""
    await _login(client)
    brain.triage_result = TriageResult(purchase_intent=True)
    extractor.result = LeadExtraction(company="ToDelete Inc")
    async with session_factory() as session:
        await repositories.insert_update(session, 705, tg_update(705, "想采购"))
        await session.commit()
    await run_process_update(session_factory, locker, sender, brain, 705)
    await run_extract_lead(session_factory, locker, sender, extractor, 705)

    resp = await client.delete("/api/users/by-telegram/500", headers=WRITE_HEADERS)
    assert resp.status_code == 200
    counts = resp.json()
    assert counts["leads"] == 1 and counts["conversations"] == 1
    assert counts["integration_jobs"] == 1

    from domain.models import AuditLog, Conversation, Message, User

    async with session_factory() as session:
        assert (await session.execute(select(User))).scalar_one_or_none() is None
        assert (await session.execute(select(Conversation))).scalar_one_or_none() is None
        assert (await session.execute(select(Message))).scalars().first() is None
        assert (await session.execute(select(Lead))).scalar_one_or_none() is None
        assert (await session.execute(select(IntegrationJob))).scalar_one_or_none() is None
        # lead 字段审计（含新旧值）已清；只剩登录/删除动作类审计
        remaining = (await session.execute(select(AuditLog))).scalars().all()
        assert all(a.entity_type != "lead" for a in remaining)
        assert any(a.action == "user_data_deleted" for a in remaining)

    assert (
        await client.delete("/api/users/by-telegram/999999", headers=WRITE_HEADERS)
    ).status_code == 404


async def test_knowledge_delete_removes_file(client, session_factory, tmp_path) -> None:
    """第三轮评审：删除文档同时删除 storage 原始文件。"""
    from pathlib import Path

    await _login(client)
    client.app.state.settings.storage_dir = str(tmp_path)
    resp = await client.post(
        "/api/knowledge/documents",
        files={"file": ("f.md", b"# doc\n\nbody", "text/markdown")},
        headers=WRITE_HEADERS,
    )
    doc_id = resp.json()["id"]
    async with session_factory() as session:
        doc = await repositories.get_document(session, doc_id)
        assert doc is not None and doc.storage_path
        stored = Path(doc.storage_path)
    assert stored.exists()  # noqa: ASYNC240
    await client.delete(f"/api/knowledge/documents/{doc_id}", headers=WRITE_HEADERS)
    assert not stored.exists()  # noqa: ASYNC240


async def test_meta_brand_public(client) -> None:
    """品牌白标（§20）：/api/meta 免认证，只暴露品牌名。"""
    resp = await client.get("/api/meta")
    assert resp.status_code == 200
    assert resp.json() == {"brand_name": ""}
    client.app.state.settings.brand_name = "Acme"
    assert (await client.get("/api/meta")).json()["brand_name"] == "Acme"


async def _seed_lead(
    session_factory, tg_id: int, *, grade: str, score: int, status: str = "open", **fields
) -> None:
    async with session_factory() as session:
        user = await repositories.upsert_user(session, {"id": tg_id, "username": f"u{tg_id}"})
        conv = await repositories.get_or_create_open_conversation(session, tg_id, user.id)
        session.add(
            Lead(
                conversation_id=conv.id,
                user_id=user.id,
                grade=grade,
                score=score,
                status=status,
                **fields,
            )
        )
        await session.commit()


async def test_metrics_overview_funnel_pending_trend(client, session_factory) -> None:
    """概览驾驶舱：漏斗/今日/趋势/待接管字段齐全且计数正确。"""
    await _login(client)
    await _seed_lead(session_factory, 90001, grade="high", score=80, external_crm_id="sheets:2")
    async with session_factory() as session:
        user = await repositories.upsert_user(session, {"id": 90002, "username": "pend"})
        conv = await repositories.get_or_create_open_conversation(session, 90002, user.id)
        conv.status = "handoff_pending"
        await session.commit()

    data = (await client.get("/api/metrics/overview?tz_offset_minutes=480")).json()
    assert data["pending_handoffs"] == 1
    assert data["funnel"]["conversations"] == 2
    assert data["funnel"]["leads"] == 1
    assert data["funnel"]["leads_high"] == 1
    assert data["funnel"]["leads_synced"] == 1
    assert data["today"] == {"conversations": 2, "leads": 1}
    assert sum(d["conversations"] for d in data["trend"]) == 2
    assert sum(d["leads"] for d in data["trend"]) == 1

    assert (await client.get("/api/metrics/pending")).json() == {"pending_handoffs": 1}


async def test_leads_filter_sort_export(client, session_factory) -> None:
    """线索 mini-CRM：状态筛选、recent 排序、CSV 导出（含 BOM、中文表头）。"""
    await _login(client)
    await _seed_lead(
        session_factory,
        90011,
        grade="high",
        score=75,
        status="synced",
        company="Acme Corp",
        external_crm_id="sheets:5",
    )
    await _seed_lead(session_factory, 90012, grade="low", score=0)

    items = (await client.get("/api/leads?status=synced")).json()["items"]
    assert [i["company"] for i in items] == ["Acme Corp"]

    items = (await client.get("/api/leads?grade=high&sort=recent")).json()["items"]
    assert items and all(i["grade"] == "high" for i in items)

    resp = await client.get("/api/leads/export?grade=high")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text.startswith("﻿")
    assert "Acme Corp" in resp.text and "Lead ID" in resp.text


async def test_channel_attribution_in_metrics_and_export(client, session_factory) -> None:
    """渠道归因闭环：overview.channels 聚合、funnel.leads_won、CSV 渠道列。"""
    await _login(client)
    async with session_factory() as session:
        user = await repositories.upsert_user(session, {"id": 90021, "username": "chan"})
        conv = await repositories.get_or_create_open_conversation(session, 90021, user.id)
        conv.source_channel = "promo_yt"
        session.add(
            Lead(
                conversation_id=conv.id,
                user_id=user.id,
                grade="high",
                score=75,
                status="won",
                company="Won Co",
                source_channel="promo_yt",
            )
        )
        await session.commit()

    data = (await client.get("/api/metrics/overview")).json()
    assert data["funnel"]["leads_won"] == 1
    row = next(c for c in data["channels"] if c["channel"] == "promo_yt")
    assert row == {"channel": "promo_yt", "conversations": 1, "leads": 1, "leads_high": 1}

    text = (await client.get("/api/leads/export")).text
    assert "渠道" in text and "promo_yt" in text


async def test_system_settings_telegram(client, session_factory, sender: FakeSender) -> None:
    """系统设置（migration 0007）：token 验证→加密入库→脱敏回显→测试通知全链路。"""
    await _login(client)
    conf = (await client.get("/api/settings/telegram")).json()
    assert conf["bot_token_source"] == "none" and conf["bot_token_masked"] == ""

    # 未配置就发测试通知 → 422
    resp = await client.post("/api/settings/telegram/test", headers=WRITE_HEADERS)
    assert resp.status_code == 422

    # 无效 token（probe 抛错）→ 422，不入库
    async def _bad_probe(token: str) -> str:
        raise ConnectionError("unauthorized")

    client.app.state.telegram_probe = _bad_probe
    resp = await client.put(
        "/api/settings/telegram", json={"bot_token": "bad-token"}, headers=WRITE_HEADERS
    )
    assert resp.status_code == 422

    # 有效 token + chat_id → 保存；PUBLIC_BASE_URL 未配 → webhook skipped
    async def _ok_probe(token: str) -> str:
        return "mercury_demo_bot"

    client.app.state.telegram_probe = _ok_probe
    resp = await client.put(
        "/api/settings/telegram",
        json={"bot_token": "123456:ABCdef", "operator_chat_id": "4242"},
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json() == {"bot_username": "mercury_demo_bot", "webhook": "skipped"}

    # 回显脱敏 + 来源 db；库里是 Fernet 密文不是明文
    conf = (await client.get("/api/settings/telegram")).json()
    assert conf["bot_token_masked"] == "****Cdef"
    assert conf["bot_token_source"] == "db"
    assert conf["operator_chat_id"] == "4242"
    from domain.models import AppSetting

    async with session_factory() as session:
        row = await session.get(AppSetting, "telegram_bot_token")
        assert row is not None and row.is_encrypted and row.value != "123456:ABCdef"

    # 测试通知走当前配置发到 chat_id
    resp = await client.post("/api/settings/telegram/test", headers=WRITE_HEADERS)
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert sender.sent[-1][0] == 4242

    # 非数字 chat_id → 422
    resp = await client.put(
        "/api/settings/telegram", json={"operator_chat_id": "@abc"}, headers=WRITE_HEADERS
    )
    assert resp.status_code == 422


async def test_system_settings_general_reflects_in_meta(client) -> None:
    """品牌后台可配：PUT general 后 /api/meta（免认证）立即返回新品牌。"""
    await _login(client)
    assert (await client.get("/api/meta")).json()["brand_name"] == ""
    resp = await client.put(
        "/api/settings/general",
        json={"brand_name": "Acme", "bot_tone_hint": "Friendly"},
        headers=WRITE_HEADERS,
    )
    assert resp.status_code == 200
    data = (await client.get("/api/settings/general")).json()
    assert data == {"brand_name": "Acme", "bot_tone_hint": "Friendly"}
    assert (await client.get("/api/meta")).json()["brand_name"] == "Acme"
