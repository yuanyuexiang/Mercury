"""FastAPI 入口：app 工厂、路由挂载、生命周期（技术方案 §3）。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import RedisSettings
from domain.config import get_settings
from fastapi import FastAPI
from observability.logging import configure_logging
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.routers import health, webhook


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.session_factory = async_sessionmaker(app.state.engine, expire_on_commit=False)
    app.state.redis = aioredis.from_url(settings.redis_url)
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await app.state.arq.aclose()
    await app.state.redis.aclose()
    await app.state.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Mercury", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(webhook.router)
    # M8: auth / conversations / leads / knowledge / metrics / settings
    return app


app = create_app()
