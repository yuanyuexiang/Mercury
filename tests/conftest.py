"""pytest fixtures（技术方案 §15）：env 提供的 postgres/redis、清库、FakeSender、会话锁。

集成测试需要 DATABASE_URL/REDIS_URL（本地 compose 或 CI services），缺省自动 skip。
Redis 测试固定用 db 15 并 flushdb，与开发队列（db 0）隔离。
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import redis.asyncio as aioredis
from integrations.locks import RedisLock
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get("DATABASE_URL")
REDIS_URL = os.environ.get("REDIS_URL")

_TABLES = (
    "messages",
    "leads",
    "handoffs",
    "integration_jobs",
    "audit_logs",
    "conversations",
    "users",
    "telegram_updates",
    "knowledge_chunks",
    "knowledge_documents",
    "llm_providers",
)


def _test_redis_url() -> str:
    assert REDIS_URL is not None
    base, _, last = REDIS_URL.rpartition("/")
    if last.isdigit():
        return f"{base}/15"
    return REDIS_URL.rstrip("/") + "/15"


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not DATABASE_URL:
        pytest.skip("需要 DATABASE_URL（本地 compose + alembic upgrade head，或 CI services）")
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def redis_client() -> AsyncIterator[aioredis.Redis]:
    if not REDIS_URL:
        pytest.skip("需要 REDIS_URL（本地 compose 或 CI services）")
    client = aioredis.from_url(_test_redis_url())
    await client.flushdb()
    yield client
    await client.aclose()


class FakeSender:
    """MessageSender 协议的测试替身：记录发送与通知。"""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.notices: list[str] = []
        self._next_id = 100

    async def send_message(self, chat_id: int, text: str) -> int:
        self.sent.append((chat_id, text))
        self._next_id += 1
        return self._next_id

    async def notify_operator(self, text: str) -> None:
        self.notices.append(text)


@pytest.fixture
def sender() -> FakeSender:
    return FakeSender()


class FakeBrain:
    """Brain 协议的测试替身：可配置 triage 结果与回答行为，记录全部调用。"""

    def __init__(self) -> None:
        from domain.schemas import TriageResult

        self.triage_result = TriageResult(risk="none", purchase_intent=False, needs_rag=True)
        self.refuse = False
        self.answer_sources = [1, 2]
        self.raise_on_triage = False
        self.raise_on_answer = False
        self.triage_calls: list[list[dict[str, str]]] = []
        self.answer_calls: list[str] = []

    async def triage(self, history: list[dict[str, str]], deadline: Any) -> Any:
        if self.raise_on_triage:
            raise RuntimeError("triage boom")
        self.triage_calls.append(history)
        return self.triage_result

    async def answer(
        self,
        session: Any,
        question: str,
        history: list[dict[str, str]],
        language: str,
        deadline: Any,
    ) -> Any:
        from domain.schemas import RagAnswer

        if self.raise_on_answer:
            raise RuntimeError("answer boom")
        self.answer_calls.append(question)
        if self.refuse:
            return RagAnswer(refused=True, source_chunk_ids=self.answer_sources)
        return RagAnswer(
            refused=False,
            text=f"回答：{question}",
            source_chunk_ids=self.answer_sources,
            model_name="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=42,
        )


@pytest.fixture
def brain() -> FakeBrain:
    return FakeBrain()


@pytest.fixture
def locker(redis_client: aioredis.Redis) -> RedisLock:
    return RedisLock(redis_client, prefix="conv", ttl_seconds=10, renew_every_seconds=3)


@pytest.fixture
def index_locker(redis_client: aioredis.Redis) -> RedisLock:
    return RedisLock(redis_client, prefix="index", ttl_seconds=10, renew_every_seconds=3)


def tg_update(
    update_id: int,
    text_content: str | None = None,
    chat_id: int = 1000,
    user_id: int = 500,
    message_id: int | None = None,
) -> dict[str, Any]:
    """构造 Telegram update payload；text_content=None 模拟非文本消息（如图片）。"""
    message: dict[str, Any] = {
        "message_id": message_id if message_id is not None else update_id,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": user_id, "first_name": "Test", "username": "tester"},
    }
    if text_content is not None:
        message["text"] = text_content
    return {"update_id": update_id, "message": message}
