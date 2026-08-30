"""FastAPI 入口：app 工厂、路由挂载、生命周期（技术方案 §3）。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from domain.config import get_settings, validate_production_settings
from fastapi import FastAPI
from integrations.app_settings import AppSettingsStore
from integrations.telegram import DynamicSender, probe_token, register_webhook
from llm.client import OpenAIChatClient, list_models
from observability.logging import configure_logging
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routers import (
    auth,
    conversations,
    health,
    knowledge,
    leads,
    meta,
    metrics,
    users,
    webhook,
)
from api.routers import (
    settings as settings_router,
)
from api.routers import (
    system as system_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_production_settings(settings)
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.session_factory = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = aioredis.from_url(settings.redis_url)
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    # 系统设置（migration 0007）：Telegram/品牌后台可配，DB 优先 env 兜底
    app.state.app_settings_store = AppSettingsStore(
        app.state.session_factory, app.state.redis, settings
    )
    app.state.app_settings_store.start_listener()
    # 人工发消息用（§9）；每次发送解析当前 token，后台改配置即生效；无 token 时打日志替身
    app.state.sender = DynamicSender(app.state.app_settings_store)
    # 保存 token 时的验证与 webhook 注册（测试中可替换为 Fake）
    app.state.telegram_probe = probe_token
    app.state.telegram_register = register_webhook
    # 供应商模型列表拉取（测试中可替换为 Fake）
    app.state.list_models = list_models
    # 供应商连接测试用；测试中可替换为 Fake（§10 /test）
    app.state.chat_client_factory = lambda base_url, api_key, model: OpenAIChatClient(
        base_url=base_url, api_key=api_key, model=model
    )
    yield
    await app.state.app_settings_store.stop_listener()
    await app.state.sender.close()
    await app.state.arq.aclose()
    await app.state.redis.aclose()
    await app.state.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Mercury", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(webhook.router)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(leads.router)
    app.include_router(knowledge.router)
    app.include_router(metrics.router)
    app.include_router(settings_router.router)
    app.include_router(system_router.router)
    app.include_router(users.router)
    return app


app = create_app()
