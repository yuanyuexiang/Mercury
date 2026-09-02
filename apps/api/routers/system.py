"""系统设置 API（migration 0007）：Telegram 对接与品牌文案，后台可配、env 兜底。

保存 bot token 前先 getMe 验证（无效 token 直接 422），成功后尽力注册 webhook；
所有写入走 AppSettingsStore（加密 + 广播失效），worker 不重启即生效。
"""

from typing import Any

import structlog
from domain import repositories
from domain.models import Conversation, KnowledgeDocument, LlmProvider, TelegramUpdate
from fastapi import APIRouter, HTTPException, Request
from integrations.app_settings import (
    KEY_BOT_TONE_HINT,
    KEY_BRAND_NAME,
    KEY_LEADS_SPREADSHEET_ID,
    KEY_OPERATOR_CHAT_ID,
    KEY_RAG_MIN_SIMILARITY,
    KEY_RAG_TOP_K,
    KEY_REPLY_DEADLINE_S,
    KEY_REVIVE_AFTER_DAYS,
    KEY_REVIVE_ENABLED,
    KEY_REVIVE_MAX_ATTEMPTS,
    KEY_SHEETS_SERVICE_ACCOUNT_JSON,
    KEY_TELEGRAM_BOT_TOKEN,
    KEY_TELEGRAM_BOT_USERNAME,
    KEY_TRIAGE_TIMEOUT_S,
    publish_invalidation,
)
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import AdminRead, AdminWrite

router = APIRouter(prefix="/api/settings", tags=["system"])
logger = structlog.get_logger()


def _mask(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"****{tail}"


@router.get("/telegram", dependencies=AdminRead)
async def get_telegram(request: Request) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    settings = request.app.state.settings
    token = await store.telegram_bot_token()
    return {
        "bot_token_masked": _mask(token),
        "bot_token_source": await store.source_of(
            KEY_TELEGRAM_BOT_TOKEN, settings.telegram_bot_token
        ),
        "operator_chat_id": await store.operator_chat_id(),
        "bot_username": await store.get(KEY_TELEGRAM_BOT_USERNAME),
        "webhook_configured": bool(settings.public_base_url and settings.telegram_webhook_secret),
    }


class TelegramPut(BaseModel):
    bot_token: str | None = None  # None/缺省 = 不改；空串 = 清除（回落 env）
    operator_chat_id: str | None = None


@router.put("/telegram", dependencies=AdminWrite)
async def put_telegram(request: Request, body: TelegramPut) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    settings = request.app.state.settings
    values: dict[str, str] = {}
    bot_username = ""

    if body.bot_token is not None:
        token = body.bot_token.strip()
        if token:
            try:
                bot_username = await request.app.state.telegram_probe(token)
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail="Bot Token 无效：Telegram 验证失败"
                ) from exc
        values[KEY_TELEGRAM_BOT_TOKEN] = token
        values[KEY_TELEGRAM_BOT_USERNAME] = bot_username if token else ""

    if body.operator_chat_id is not None:
        chat_id = body.operator_chat_id.strip()
        if chat_id and not chat_id.lstrip("-").isdigit():
            raise HTTPException(status_code=422, detail="通知接收 Chat ID 必须是数字")
        values[KEY_OPERATOR_CHAT_ID] = chat_id

    if not values:
        raise HTTPException(status_code=422, detail="没有要保存的字段")
    await store.set_values(values)
    await publish_invalidation(request.app.state.redis)

    # token 保存成功后尽力注册 webhook（缺 PUBLIC_BASE_URL/secret 时跳过，不算失败）
    webhook_status = "unchanged"
    new_token = values.get(KEY_TELEGRAM_BOT_TOKEN)
    if new_token:
        if settings.public_base_url and settings.telegram_webhook_secret:
            try:
                await request.app.state.telegram_register(
                    new_token, settings.public_base_url, settings.telegram_webhook_secret
                )
                webhook_status = "registered"
            except Exception:
                logger.exception("webhook_register_failed")
                webhook_status = "failed"
        else:
            webhook_status = "skipped"

    async with request.app.state.session_factory() as session:
        await repositories.add_audit(
            session,
            "admin",
            "telegram_settings_update",
            "app_setting",
            0,
            {"fields": sorted(values), "webhook": webhook_status},  # 绝不记录 token 明文
        )
        await session.commit()
    return {"bot_username": bot_username, "webhook": webhook_status}


@router.post("/telegram/test", dependencies=AdminWrite)
async def test_telegram(request: Request) -> dict[str, Any]:
    """给通知接收人发一条测试消息，验证 token + chat_id 全链路。"""
    store = request.app.state.app_settings_store
    token = await store.telegram_bot_token()
    chat_id = await store.operator_chat_id()
    if not token:
        raise HTTPException(status_code=422, detail="请先配置 Bot Token")
    if not chat_id:
        raise HTTPException(status_code=422, detail="请先配置通知接收 Chat ID")
    try:
        await request.app.state.sender.send_message(
            int(chat_id), "✅ Mercury 测试通知：Telegram 对接正常。"
        )
    except Exception as exc:
        logger.exception("telegram_test_failed")
        raise HTTPException(
            status_code=502, detail="发送失败：请检查 Chat ID 是否正确、是否已与机器人对话过"
        ) from exc
    return {"ok": True}


@router.get("/setup-status", dependencies=AdminRead)
async def setup_status(request: Request) -> dict[str, Any]:
    """接入进度（快速开始清单用）：四项是否已配置，全 true = 可开门迎客。"""
    store = request.app.state.app_settings_store
    settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        active_provider = (
            await session.execute(select(LlmProvider).where(LlmProvider.is_active))
        ).scalar_one_or_none()
        knowledge_active = (
            await session.execute(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.status == "active")
            )
        ).scalar() or 0
        embed_providers = (
            await session.execute(
                select(func.count())
                .select_from(LlmProvider)
                .where(LlmProvider.is_embed_active, LlmProvider.embed_model.is_not(None))
            )
        ).scalar() or 0
    # 知识库检索（embedding）可用性：检索槽已选定服务商（可与对话槽不同家），
    # 或 env 有兜底 key——缺失时上传的文档无法索引，界面必须显式警告
    embedding_ready = bool(embed_providers or settings.llm_api_key)
    return {
        "telegram": bool(await store.telegram_bot_token()),
        "operator": bool(await store.operator_chat_id()),
        "llm": active_provider is not None
        or bool(settings.llm_api_key and settings.llm_chat_model),
        "knowledge": knowledge_active > 0,
        "embedding_ready": embedding_ready,
        "bot_username": await store.get(KEY_TELEGRAM_BOT_USERNAME),
    }


@router.get("/telegram/candidates", dependencies=AdminRead)
async def telegram_candidates(request: Request) -> dict[str, Any]:
    """通知接收人自动检测：从最近 webhook 消息里提取发信 chat 供点选——
    客户给机器人发一句话即可，无需 curl getUpdates。"""
    async with request.app.state.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(TelegramUpdate).order_by(TelegramUpdate.update_id.desc()).limit(50)
                )
            )
            .scalars()
            .all()
        )
    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        message = (row.payload or {}).get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None or chat_id in seen:
            continue
        seen.add(chat_id)
        sender = message.get("from") or {}
        if chat.get("type") == "private":
            name = sender.get("first_name") or sender.get("username") or str(chat_id)
            if sender.get("username"):
                name = f"{name}（@{sender['username']}）"
        else:
            name = chat.get("title") or f"群 {chat_id}"
        items.append(
            {
                "chat_id": chat_id,
                "kind": "私聊" if chat.get("type") == "private" else "群组",
                "name": name,
                "last_text": (message.get("text") or "")[:50],
                "received_at": row.received_at.isoformat(),
            }
        )
        if len(items) >= 5:
            break
    # 防呆（2026-09-02）：候选大多来自客户流量——标记"已是客户会话"的 chat，
    # 前端警示，避免管理员误把内部通知配到某个客户的私聊里
    if items:
        async with request.app.state.session_factory() as session:
            rows2 = (
                await session.execute(
                    select(Conversation.telegram_chat_id).where(
                        Conversation.telegram_chat_id.in_([c["chat_id"] for c in items])
                    )
                )
            ).all()
        customer_ids = {r[0] for r in rows2}
        for c in items:
            c["is_customer"] = c["chat_id"] in customer_ids
    return {"items": items}


@router.get("/revive", dependencies=AdminRead)
async def get_revive(request: Request) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    return {
        "enabled": await store.revive_enabled(),
        "after_days": await store.revive_after_days(),
        "max_attempts": await store.revive_max_attempts(),
    }


class RevivePut(BaseModel):
    enabled: bool | None = None
    after_days: int | None = None  # 1–60
    max_attempts: int | None = None  # 0–5


@router.put("/revive", dependencies=AdminWrite)
async def put_revive(request: Request, body: RevivePut) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    values: dict[str, str] = {}
    if body.enabled is not None:
        values[KEY_REVIVE_ENABLED] = "true" if body.enabled else "false"
    if body.after_days is not None:
        if not 1 <= body.after_days <= 60:
            raise HTTPException(status_code=422, detail="安静天数需在 1–60 之间")
        values[KEY_REVIVE_AFTER_DAYS] = str(body.after_days)
    if body.max_attempts is not None:
        if not 0 <= body.max_attempts <= 5:
            raise HTTPException(status_code=422, detail="跟进次数需在 0–5 之间")
        values[KEY_REVIVE_MAX_ATTEMPTS] = str(body.max_attempts)
    if not values:
        raise HTTPException(status_code=422, detail="没有要保存的字段")
    await store.set_values(values)
    await publish_invalidation(request.app.state.redis)
    return await get_revive(request)


@router.get("/tuning", dependencies=AdminRead)
async def get_tuning(request: Request) -> dict[str, Any]:
    """回复与检索调优（§13 调优参数后台化）：DB 优先 env/代码默认兜底，保存即热生效。"""
    store = request.app.state.app_settings_store
    return {
        "rag_min_similarity": await store.rag_min_similarity(),
        "rag_top_k": await store.rag_top_k(),
        "reply_deadline_s": await store.reply_deadline_s(),
        "triage_timeout_s": await store.triage_timeout_s(),
    }


class TuningPut(BaseModel):
    rag_min_similarity: float | None = None  # 0.05–0.95
    rag_top_k: int | None = None  # 1–20
    reply_deadline_s: float | None = None  # 3–60
    triage_timeout_s: float | None = None  # 0.5–20


@router.put("/tuning", dependencies=AdminWrite)
async def put_tuning(request: Request, body: TuningPut) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    values: dict[str, str] = {}
    if body.rag_min_similarity is not None:
        if not 0.05 <= body.rag_min_similarity <= 0.95:
            raise HTTPException(status_code=422, detail="相似度阈值需在 0.05–0.95 之间")
        values[KEY_RAG_MIN_SIMILARITY] = str(body.rag_min_similarity)
    if body.rag_top_k is not None:
        if not 1 <= body.rag_top_k <= 20:
            raise HTTPException(status_code=422, detail="检索条数需在 1–20 之间")
        values[KEY_RAG_TOP_K] = str(body.rag_top_k)
    if body.reply_deadline_s is not None:
        if not 3 <= body.reply_deadline_s <= 60:
            raise HTTPException(status_code=422, detail="回复预算需在 3–60 秒之间")
        values[KEY_REPLY_DEADLINE_S] = str(body.reply_deadline_s)
    if body.triage_timeout_s is not None:
        if not 0.5 <= body.triage_timeout_s <= 20:
            raise HTTPException(status_code=422, detail="意图识别上限需在 0.5–20 秒之间")
        values[KEY_TRIAGE_TIMEOUT_S] = str(body.triage_timeout_s)
    if not values:
        raise HTTPException(status_code=422, detail="没有要保存的字段")
    await store.set_values(values)
    await publish_invalidation(request.app.state.redis)
    return await get_tuning(request)


@router.get("/sheets", dependencies=AdminRead)
async def get_sheets(request: Request) -> dict[str, Any]:
    """Google Sheets 同步配置状态：凭据只回传 client_email，绝不回传私钥。"""
    from integrations.sheets import parse_service_account

    store = request.app.state.app_settings_store
    raw = await store.sheets_service_account_json()
    email = None
    if raw:
        try:
            email = parse_service_account(raw).get("client_email")
        except ValueError:
            email = None
    return {
        "configured": bool(raw) and bool(await store.leads_spreadsheet_id()),
        "service_account_email": email,
        "spreadsheet_id": await store.leads_spreadsheet_id(),
    }


class SheetsPut(BaseModel):
    service_account_json: str | None = None  # 留空/不传 = 保留原值；粘贴整段 JSON
    spreadsheet_id: str | None = None


@router.put("/sheets", dependencies=AdminWrite)
async def put_sheets(request: Request, body: SheetsPut) -> dict[str, Any]:
    from integrations.sheets import parse_service_account

    store = request.app.state.app_settings_store
    values: dict[str, str] = {}
    if body.service_account_json:
        try:
            parsed = parse_service_account(body.service_account_json)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not parsed.get("client_email") or not parsed.get("private_key"):
            raise HTTPException(
                status_code=422,
                detail="JSON 缺少 client_email / private_key，请粘贴完整的密钥文件内容",
            )
        values[KEY_SHEETS_SERVICE_ACCOUNT_JSON] = body.service_account_json.strip()
    if body.spreadsheet_id is not None:
        values[KEY_LEADS_SPREADSHEET_ID] = body.spreadsheet_id.strip()
    if not values:
        raise HTTPException(status_code=422, detail="没有要保存的字段")
    await store.set_values(values)
    await publish_invalidation(request.app.state.redis)
    async with request.app.state.session_factory() as session:
        await repositories.add_audit(
            session,
            "admin",
            "sheets_config_updated",
            "app_setting",
            0,
            {"fields": sorted(values)},  # 绝不记录凭据内容
        )
        await session.commit()
    return await get_sheets(request)


@router.post("/sheets/test", dependencies=AdminWrite)
async def test_sheets(request: Request) -> dict[str, Any]:
    """实测连接：打开表并确保 Leads 工作表与表头就绪，返回表标题。"""
    import asyncio as _asyncio

    from integrations.sheets import GoogleSheetsLeadSync, parse_service_account

    store = request.app.state.app_settings_store
    raw = await store.sheets_service_account_json()
    spreadsheet_id = await store.leads_spreadsheet_id()
    if not raw or not spreadsheet_id:
        raise HTTPException(status_code=422, detail="请先保存凭据 JSON 和表 ID")
    try:
        sync = GoogleSheetsLeadSync(parse_service_account(raw), spreadsheet_id)
        title = await _asyncio.wait_for(_asyncio.to_thread(sync.probe), timeout=20)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("sheets_test_failed", error=repr(exc)[:200])
        raise HTTPException(
            status_code=502,
            detail=(
                "连接失败：确认已启用 Google Sheets API，"
                "且表格已共享给 service account 邮箱（编辑者权限）"
            ),
        ) from exc
    return {"ok": True, "spreadsheet_title": title}


@router.get("/general", dependencies=AdminRead)
async def get_general(request: Request) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    return {
        "brand_name": await store.brand_name(),
        "bot_tone_hint": await store.bot_tone_hint(),
    }


class GeneralPut(BaseModel):
    brand_name: str | None = None
    bot_tone_hint: str | None = None


@router.put("/general", dependencies=AdminWrite)
async def put_general(request: Request, body: GeneralPut) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    values: dict[str, str] = {}
    if body.brand_name is not None:
        values[KEY_BRAND_NAME] = body.brand_name.strip()[:64]
    if body.bot_tone_hint is not None:
        values[KEY_BOT_TONE_HINT] = body.bot_tone_hint.strip()[:500]
    if not values:
        raise HTTPException(status_code=422, detail="没有要保存的字段")
    await store.set_values(values)
    await publish_invalidation(request.app.state.redis)
    return {
        "brand_name": await store.brand_name(),
        "bot_tone_hint": await store.bot_tone_hint(),
    }
