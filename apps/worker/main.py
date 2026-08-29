"""arq WorkerSettings：任务注册、cron、生命周期（技术方案 §3/§6）。

启动：uv run arq worker.main.WorkerSettings
"""

from typing import Any

import redis.asyncio as aioredis
from arq import cron
from arq.connections import RedisSettings
from domain.config import get_settings
from integrations.locks import RedisLock
from integrations.sheets import build_lead_sync
from integrations.telegram import build_sender
from llm.brain import ConversationSummarizer, RagBrain
from llm.client import build_embedder
from llm.extraction import LlmLeadExtractor
from llm.provider_config import DynamicChatClient, ProviderSource
from observability.logging import configure_logging
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from worker.tasks.extract_lead import extract_lead
from worker.tasks.index_document import index_document
from worker.tasks.process_update import process_update
from worker.tasks.sweeper import retention_cleanup, sweep
from worker.tasks.sync_lead import sync_lead


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
    # chat 经 DynamicChatClient：DB 激活供应商优先、env 兜底，后台切换不重启即生效（§12）
    provider_source = ProviderSource(ctx["session_factory"], redis_client, settings)
    provider_source.start_listener()
    ctx["provider_source"] = provider_source
    chat = DynamicChatClient(provider_source)
    embedder = build_embedder(settings)  # embedding 仅 env 配置（§12）
    ctx["embedder"] = embedder  # None → 索引任务明确失败
    ctx["brain"] = RagBrain(chat, embedder, settings) if embedder else None
    ctx["extractor"] = LlmLeadExtractor(chat)
    ctx["summarizer"] = ConversationSummarizer(chat)
    ctx["sync_port"] = build_lead_sync(settings)  # None → 同步任务走 retry 等待配置


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["provider_source"].stop_listener()
    await ctx["sender"].close()
    await ctx["redis_client"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [process_update, extract_lead, index_document, sync_lead]
    cron_jobs = [
        cron(sweep, second=0),  # 每分钟一次（§6 兜底扫描器）
        cron(retention_cleanup, hour=4, minute=0),  # 每日数据保留期清理（§14）
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
