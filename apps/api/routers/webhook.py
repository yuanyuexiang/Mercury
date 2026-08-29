"""POST /webhooks/telegram/{bot_secret}（技术方案 §5）。

职责只有三件：双重校验、幂等落库、入队——毫秒级返回 200。
入队失败的窗口由 worker 兜底扫描器闭环，这里绝不因内部错误返回 5xx。
"""

import secrets

import structlog
from domain import repositories
from fastapi import APIRouter, HTTPException, Request
from observability.logging import new_trace_id

router = APIRouter(tags=["webhook"])
logger = structlog.get_logger()


@router.post("/webhooks/telegram/{bot_secret}")
async def telegram_webhook(bot_secret: str, request: Request) -> dict[str, bool]:
    expected = request.app.state.settings.telegram_webhook_secret
    header_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not expected or not (
        secrets.compare_digest(bot_secret, expected)
        and secrets.compare_digest(header_secret, expected)
    ):
        raise HTTPException(status_code=404)

    try:
        payload = await request.json()
        update_id = payload.get("update_id")
        if not isinstance(update_id, int):
            logger.warning("webhook_payload_without_update_id")
            return {"ok": True}

        trace_id = new_trace_id()
        async with request.app.state.session_factory() as session:
            inserted = await repositories.insert_update(session, update_id, payload)
            await session.commit()
        if inserted:
            await request.app.state.arq.enqueue_job(
                "process_update", update_id, trace_id, _job_id=f"process_update:{update_id}"
            )
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        # 已落库的 update 由扫描器兜底；未落库的 Telegram 会重推（我们没吞掉它的重试机会）
        logger.exception("webhook_internal_error")
        return {"ok": True}
