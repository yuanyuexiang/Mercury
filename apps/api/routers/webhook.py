"""POST /webhooks/telegram/{bot_secret}（技术方案 §5）。

失败语义（第三轮评审修订）：
- 数据库未提交 → 返回 503，让 Telegram 重推（消息还不在我们手里，绝不能吞）；
- 已提交、入队失败 → 返回 200，兜底扫描器恢复（update 已进表，必然被处理）。
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
    except Exception:
        logger.warning("webhook_unparseable_payload")
        return {"ok": True}  # 畸形请求重推也不会更好，直接吞
    if not isinstance(update_id, int):
        logger.warning("webhook_payload_without_update_id")
        return {"ok": True}

    trace_id = new_trace_id()
    try:
        async with request.app.state.session_factory() as session:
            inserted = await repositories.insert_update(session, update_id, payload)
            await session.commit()
    except Exception as exc:
        # 未落库：5xx 触发 Telegram 重推——消息不在我们手里，不能返回成功
        logger.exception("webhook_db_write_failed", update_id=update_id)
        raise HTTPException(status_code=503, detail="temporarily unavailable") from exc

    if inserted:
        try:
            await request.app.state.arq.enqueue_job(
                "process_update", update_id, trace_id, _job_id=f"process_update:{update_id}"
            )
        except Exception:
            # 已落库：扫描器②会补入队，返回 200 避免 Telegram 重推造成重复
            logger.exception("webhook_enqueue_failed_sweeper_will_recover", update_id=update_id)
    return {"ok": True}
