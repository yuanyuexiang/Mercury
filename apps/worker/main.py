"""arq WorkerSettings：任务注册、cron、生命周期（技术方案 §3/§6）。

启动：uv run arq worker.main.WorkerSettings
"""

from typing import Any

import redis.asyncio as aioredis
from arq import cron
from arq.connections import RedisSettings
from domain.config import get_settings, validate_production_settings
from integrations.app_settings import AppSettingsStore
from integrations.locks import RedisLock
from integrations.sheets import build_lead_sync
from integrations.telegram import DynamicSender
from llm.brain import ConversationSummarizer, RagBrain
from llm.extraction import LlmLeadExtractor
from llm.provider_config import DynamicChatClient, DynamicEmbedder, ProviderSource
from observability.logging import configure_logging
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from worker.tasks.extract_lead import extract_lead
from worker.tasks.index_document import index_document
from worker.tasks.process_update import process_update
from worker.tasks.revive import revive_sleeping_leads
from worker.tasks.sweeper import retention_cleanup, sweep
from worker.tasks.sync_lead import sync_lead


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    validate_production_settings(settings)
    configure_logging(settings.log_level)
    ctx["settings"] = settings
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)
    redis_client = aioredis.from_url(settings.redis_url)
    ctx["redis_client"] = redis_client
    ctx["locker"] = RedisLock(redis_client, prefix="conv")
    ctx["index_locker"] = RedisLock(redis_client, prefix="index", ttl_seconds=120)
    app_settings = AppSettingsStore(ctx["session_factory"], redis_client, settings)
    app_settings.start_listener()
    ctx["app_settings"] = app_settings
    # 每次发送解析当前 token/chat_id（后台可配，migration 0007）；无 token 时打日志替身
    ctx["sender"] = DynamicSender(app_settings)
    # chat 经 DynamicChatClient：DB 激活供应商优先、env 兜底，后台切换不重启即生效（§12）
    provider_source = ProviderSource(ctx["session_factory"], redis_client, settings)
    provider_source.start_listener()
    ctx["provider_source"] = provider_source
    chat = DynamicChatClient(provider_source)
    embedder = DynamicEmbedder(provider_source, settings)  # DB 供应商优先，env 兜底（§12 修订）
    ctx["embedder"] = embedder

    # branding 动态读取：后台改品牌/语气，RAG 提示词即生效
    async def _branding() -> tuple[str, str]:
        return await app_settings.brand_name(), await app_settings.bot_tone_hint()

    ctx["brain"] = RagBrain(
        chat, embedder, settings, branding=_branding
    )  # 未配置时调用抛 LlmNotConfiguredError，编排层降级
    ctx["extractor"] = LlmLeadExtractor(chat)
    ctx["summarizer"] = ConversationSummarizer(chat)
    ctx["sync_port"] = build_lead_sync(settings)  # None → 同步任务走 retry 等待配置


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["app_settings"].stop_listener()
    await ctx["provider_source"].stop_listener()
    await ctx["sender"].close()
    await ctx["redis_client"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [process_update, extract_lead, index_document, sync_lead]
    cron_jobs = [
        cron(sweep, second=0),  # 每分钟一次（§6 兜底扫描器）
        cron(retention_cleanup, hour=4, minute=0),  # 每日数据保留期清理（§14）
        # 沉睡线索唤醒：每日 UTC 02:30（北京 10:30，工作时间不深夜打扰）
        cron(revive_sleeping_leads, hour=2, minute=30),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
