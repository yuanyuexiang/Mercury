"""FastAPI 依赖注入：设置、引擎、Redis、管理员认证、CSRF（技术方案 §10/§14）。"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from domain.config import Settings
from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

COOKIE_NAME = "mercury_session"
JWT_TTL_HOURS = 24


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> AsyncEngine:
    return request.app.state.engine


def get_redis(request: Request) -> Redis:
    return request.app.state.redis


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def issue_session_token(settings: Settings) -> str:
    payload = {
        "sub": settings.admin_username,
        "exp": datetime.now(UTC) + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def require_admin(request: Request) -> str:
    """cookie JWT 校验（§10）；写接口另需 require_csrf。"""
    settings: Settings = request.app.state.settings
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="会话无效或已过期") from exc
    return str(payload.get("sub", ""))


def require_csrf(request: Request) -> None:
    """CSRF 防线（§14）：写接口要求自定义头——跨站表单无法携带自定义头。"""
    if request.headers.get("x-requested-with") != "fetch":
        raise HTTPException(status_code=403, detail="缺少 CSRF 防护头")


AdminWrite = [Depends(require_admin), Depends(require_csrf)]
AdminRead = [Depends(require_admin)]
