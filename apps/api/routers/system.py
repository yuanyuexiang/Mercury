"""系统设置 API（migration 0007）：Telegram 对接与品牌文案，后台可配、env 兜底。

保存 bot token 前先 getMe 验证（无效 token 直接 422），成功后尽力注册 webhook；
所有写入走 AppSettingsStore（加密 + 广播失效），worker 不重启即生效。
"""

from typing import Any

import structlog
from domain import repositories
from domain.models import KnowledgeDocument, LlmProvider, TelegramUpdate
from fastapi import APIRouter, HTTPException, Request
from integrations.app_settings import (
    KEY_BOT_TONE_HINT,
    KEY_BRAND_NAME,
    KEY_OPERATOR_CHAT_ID,
    KEY_REVIVE_AFTER_DAYS,
    KEY_REVIVE_ENABLED,
    KEY_REVIVE_MAX_ATTEMPTS,
    KEY_TELEGRAM_BOT_TOKEN,
    KEY_TELEGRAM_BOT_USERNAME,
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
    # 知识库检索（embedding）可用性：激活供应商配了 embed_model，或 env 有兜底 key——
    # 缺失时上传的文档无法索引，必须在界面上显式警告（小白陷阱）
    embedding_ready = bool(
        (active_provider is not None and active_provider.embed_model) or settings.llm_api_key
    )
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
