"""§5 webhook：双重校验、幂等落库、只入队一次（M2 验收：重复推送不产生重复记录）。"""

from typing import Any

import httpx
from api.main import create_app
from domain.config import Settings
from domain.models import TelegramUpdate
from sqlalchemy import func, select

from tests.conftest import tg_update

SECRET = "test-webhook-secret-0123456789abcdef"


class StubArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((name, args))


def make_app(session_factory: Any) -> tuple[Any, StubArq]:
    app = create_app()
    app.state.settings = Settings(telegram_webhook_secret=SECRET)
    app.state.session_factory = session_factory
    arq = StubArq()
    app.state.arq = arq
    return app, arq


async def _post(app: Any, path_secret: str, header_secret: str, payload: dict[str, Any]):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            f"/webhooks/telegram/{path_secret}",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": header_secret},
        )


async def test_wrong_secret_404(session_factory) -> None:
    app, arq = make_app(session_factory)
    assert (await _post(app, "wrong", SECRET, tg_update(1, "hi"))).status_code == 404
    assert (await _post(app, SECRET, "wrong", tg_update(1, "hi"))).status_code == 404
    assert arq.jobs == []


async def test_accept_and_enqueue_once(session_factory) -> None:
    app, arq = make_app(session_factory)
    resp = await _post(app, SECRET, SECRET, tg_update(42, "hello"))
    assert resp.status_code == 200 and resp.json() == {"ok": True}

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(TelegramUpdate))).scalar()
    assert count == 1
    assert len(arq.jobs) == 1 and arq.jobs[0][1][0] == 42


async def test_duplicate_push_no_duplicate_rows(session_factory) -> None:
    """M2 验收标准：同一 update_id 推两次 → 一行记录、一次入队。"""
    app, arq = make_app(session_factory)
    for _ in range(3):
        resp = await _post(app, SECRET, SECRET, tg_update(7, "dup"))
        assert resp.status_code == 200

    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(TelegramUpdate))).scalar()
    assert count == 1
    assert len(arq.jobs) == 1


async def test_db_failure_returns_503_so_telegram_retries(session_factory) -> None:
    """第三轮评审：数据库未落库必须 5xx——返回 200 会让 Telegram 放弃重推、消息永久丢失。"""

    class BrokenFactory:
        def __call__(self):
            raise ConnectionError("db down")

    app, arq = make_app(BrokenFactory())
    resp = await _post(app, SECRET, SECRET, tg_update(9, "hello"))
    assert resp.status_code == 503
    assert arq.jobs == []


async def test_enqueue_failure_still_200(session_factory) -> None:
    """已落库、入队失败 → 200（扫描器兜底），不能让 Telegram 重推造成重复。"""

    class BrokenArq:
        async def enqueue_job(self, *args, **kwargs):
            raise ConnectionError("redis down")

    app, _ = make_app(session_factory)
    app.state.arq = BrokenArq()
    resp = await _post(app, SECRET, SECRET, tg_update(10, "hello"))
    assert resp.status_code == 200
    async with session_factory() as session:
        from sqlalchemy import select

        row = (await session.execute(select(TelegramUpdate))).scalar_one()
        assert row.status == "queued"  # 进了表，扫描器②会补入队
