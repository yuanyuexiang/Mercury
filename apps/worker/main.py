"""arq WorkerSettings：任务注册、cron、生命周期（技术方案 §3/§6）。

启动：uv run arq worker.main.WorkerSettings
"""

from typing import Any

import redis.asyncio as aioredis
from arq import cron
from arq.connections import RedisSettings
from domain.config import get_settings
from integrations.locks import RedisLock
from integrations.telegram import build_sender
from llm.brain import RagBrain
from llm.client import build_chat_client, build_embedder
from llm.extraction import LlmLeadExtractor
from observability.logging import configure_logging
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from worker.tasks.extract_lead import extract_lead
from worker.tasks.index_document import index_document
from worker.tasks.process_update import process_update
from worker.tasks.sweeper import sweep


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    ctx["settings"] = settings
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)
    redis_client = aioredis.from_url(settings.redis_url)
    ctx["redis_client"] = redis_client
    ctx["locker"] = RedisLock(redis_client, prefix="conv")
    ctx["index_locker"] = RedisLock(redis_client, prefix="index", ttl_seconds=120)
    ctx["sender"] = build_sender(settings.telegram_bot_token, settings.operator_telegram_chat_id)
    # LLM 依赖共享同一 chat client；缺 key/模型名时为 None → 各自安全降级
    chat = build_chat_client(settings)
    embedder = build_embedder(settings)
    ctx["embedder"] = embedder  # None → 索引任务明确失败
    ctx["brain"] = RagBrain(chat, embedder, settings) if chat and embedder else None
    ctx["extractor"] = LlmLeadExtractor(chat) if chat else None


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["sender"].close()
    await ctx["redis_client"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [process_update, extract_lead, index_document]
    cron_jobs = [cron(sweep, second=0)]  # 每分钟一次（§6 兜底扫描器）
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
