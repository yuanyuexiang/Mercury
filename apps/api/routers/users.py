"""用户数据删除 API（技术方案 §14）：按 Telegram user ID 删除全部关联数据。"""

import structlog
from domain import repositories
from fastapi import APIRouter, HTTPException, Request

from api.deps import AdminWrite

router = APIRouter(prefix="/api/users", tags=["users"])
logger = structlog.get_logger()


@router.delete("/by-telegram/{telegram_user_id}", dependencies=AdminWrite)
async def delete_user(request: Request, telegram_user_id: int) -> dict[str, int]:
    async with request.app.state.session_factory() as session:
        removed = await repositories.delete_user_data(session, telegram_user_id)
        if removed is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        # 删除动作本身留一条匿名审计（不含任何用户内容）
        await repositories.add_audit(
            session, "admin", "user_data_deleted", "user", 0, {"counts": removed}
        )
        await session.commit()
    logger.info("user_data_deleted", **removed)
    return removed
