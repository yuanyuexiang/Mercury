"""模型供应商配置 API（技术方案 §10/§12）：增删改、激活（广播失效）、连接测试；key 永不回传。"""

import time
from typing import Any

import structlog
from domain import repositories
from domain.models import LlmProvider
from fastapi import APIRouter, HTTPException, Request
from llm.provider_config import decrypt_api_key, encrypt_api_key, publish_invalidation
from pydantic import BaseModel
from sqlalchemy import func, select, update

from api.deps import AdminRead, AdminWrite
from api.netguard import assert_public_http_url

router = APIRouter(prefix="/api/settings/llm-providers", tags=["settings"])
logger = structlog.get_logger()


def _provider_out(p: LlmProvider) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "api_key_masked": f"****{p.api_key_enc[-4:]}" if p.api_key_enc else "",
        "chat_model": p.chat_model,
        "fallback_model": p.fallback_model,
        "embed_model": p.embed_model,
        "supports_json_schema": p.supports_json_schema,
        "is_active": p.is_active,
        "last_test_at": p.last_test_at.isoformat() if p.last_test_at else None,
        "last_test_ok": p.last_test_ok,
    }


@router.get("", dependencies=AdminRead)
async def list_providers(request: Request) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        rows = (await session.execute(select(LlmProvider).order_by(LlmProvider.id))).scalars().all()
    return {"items": [_provider_out(p) for p in rows]}


class ProviderCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    chat_model: str
    fallback_model: str = ""
    embed_model: str = ""  # 空 = embedding 用 env 兜底；必须为 1536 维模型
    supports_json_schema: bool = True


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # 传了才更新密文，不传保留（§10）
    chat_model: str | None = None
    fallback_model: str | None = None
    embed_model: str | None = None
    supports_json_schema: bool | None = None


def _check_base_url(request: Request, base_url: str) -> None:
    settings = request.app.state.settings
    assert_public_http_url(base_url, allow_private=settings.allow_private_llm_base_url)


class ModelsQuery(BaseModel):
    """拉取模型列表：已存供应商传 provider_id（用库里密文 key）；新建未保存传 base_url+api_key。"""

    provider_id: int | None = None
    base_url: str | None = None
    api_key: str | None = None


@router.post("/models", dependencies=AdminWrite)
async def fetch_models(request: Request, body: ModelsQuery) -> dict[str, Any]:
    settings = request.app.state.settings
    if body.provider_id is not None:
        async with request.app.state.session_factory() as session:
            provider = await session.get(LlmProvider, body.provider_id)
            if provider is None:
                raise HTTPException(status_code=404)
        base_url = provider.base_url
        api_key = body.api_key or decrypt_api_key(settings, provider.api_key_enc)
    else:
        if not body.base_url or not body.api_key:
            raise HTTPException(status_code=422, detail="请先填写 Base URL 和 API Key")
        base_url = body.base_url
        api_key = body.api_key
    _check_base_url(request, base_url)
    try:
        models = await request.app.state.list_models(base_url, api_key)
    except Exception as exc:
        logger.warning("list_models_failed", base_url=base_url)
        raise HTTPException(
            status_code=502, detail="拉取失败：请检查 Base URL 与 API Key 是否正确"
        ) from exc
    return {"items": models}


@router.post("", dependencies=AdminWrite)
async def create_provider(request: Request, body: ProviderCreate) -> dict[str, Any]:
    _check_base_url(request, body.base_url)
    settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        provider = LlmProvider(
            name=body.name,
            base_url=body.base_url,
            api_key_enc=encrypt_api_key(settings, body.api_key),
            chat_model=body.chat_model,
            fallback_model=body.fallback_model or None,
            embed_model=body.embed_model or None,
            supports_json_schema=body.supports_json_schema,
        )
        session.add(provider)
        await repositories.add_audit(
            session, "admin", "provider_created", "llm_provider", 0, {"name": body.name}
        )
        await session.commit()
        return _provider_out(provider)


@router.patch("/{provider_id}", dependencies=AdminWrite)
async def patch_provider(request: Request, provider_id: int, body: ProviderPatch) -> dict[str, Any]:
    settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        provider = await session.get(LlmProvider, provider_id)
        if provider is None:
            raise HTTPException(status_code=404)
        updates = body.model_dump(exclude_unset=True)
        if "api_key" in updates:
            plaintext = updates.pop("api_key")
            if plaintext:
                updates["api_key_enc"] = encrypt_api_key(settings, plaintext)
        if "base_url" in updates:
            _check_base_url(request, updates["base_url"])
        if "fallback_model" in updates and not updates["fallback_model"]:
            updates["fallback_model"] = None
        if "embed_model" in updates and not updates["embed_model"]:
            updates["embed_model"] = None
        for key, value in updates.items():
            setattr(provider, key, value)
        provider.updated_at = func.now()  # type: ignore[assignment]
        await repositories.add_audit(
            session,
            "admin",
            "provider_updated",
            "llm_provider",
            provider.id,
            {"fields": [k for k in updates if k != "api_key_enc"]},
        )
        await session.commit()
        await publish_invalidation(request.app.state.redis)
        await session.refresh(provider)
        return _provider_out(provider)


@router.post("/{provider_id}/activate", dependencies=AdminWrite)
async def activate_provider(request: Request, provider_id: int) -> dict[str, Any]:
    """激活（全局唯一）并广播失效——worker 不重启即切换（M8 验收项）。"""
    async with request.app.state.session_factory() as session:
        provider = await session.get(LlmProvider, provider_id)
        if provider is None:
            raise HTTPException(status_code=404)
        await session.execute(update(LlmProvider).values(is_active=False))
        provider.is_active = True
        await repositories.add_audit(
            session,
            "admin",
            "provider_activated",
            "llm_provider",
            provider.id,
            {"name": provider.name},
        )
        await session.commit()
    await publish_invalidation(request.app.state.redis)
    return {"ok": True, "active_id": provider_id}


@router.post("/{provider_id}/test", dependencies=AdminWrite)
async def test_provider(request: Request, provider_id: int) -> dict[str, Any]:
    """最小对话调用（§10）：回填 last_test_*，避免填错 key 等到真实用户消息才发现。"""
    settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        provider = await session.get(LlmProvider, provider_id)
        if provider is None:
            raise HTTPException(status_code=404)
        base_url, model = provider.base_url, provider.chat_model
        api_key = decrypt_api_key(settings, provider.api_key_enc)

    began = time.monotonic()
    ok, error = True, None
    try:
        chat_factory = request.app.state.chat_client_factory
        client = chat_factory(base_url, api_key, model)
        await client.chat(
            [{"role": "user", "content": "ping — reply with 'pong' only"}],
            purpose="test",
            timeout_s=15.0,
        )
    except Exception as exc:
        ok, error = False, repr(exc)[:300]
    latency_ms = int((time.monotonic() - began) * 1000)

    async with request.app.state.session_factory() as session:
        await session.execute(
            update(LlmProvider)
            .where(LlmProvider.id == provider_id)
            .values(last_test_at=func.now(), last_test_ok=ok)
        )
        await session.commit()
    return {"ok": ok, "latency_ms": latency_ms, "error": error}


@router.delete("/{provider_id}", dependencies=AdminWrite)
async def delete_provider(request: Request, provider_id: int) -> dict[str, bool]:
    async with request.app.state.session_factory() as session:
        provider = await session.get(LlmProvider, provider_id)
        if provider is None:
            raise HTTPException(status_code=404)
        if provider.is_active:
            raise HTTPException(
                status_code=409, detail="激活中的供应商不可删除，请先激活其他供应商"
            )
        await repositories.add_audit(
            session,
            "admin",
            "provider_deleted",
            "llm_provider",
            provider.id,
            {"name": provider.name},
        )
        await session.delete(provider)
        await session.commit()
    return {"ok": True}
