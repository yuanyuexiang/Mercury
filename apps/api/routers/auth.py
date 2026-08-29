"""登录/登出：bcrypt + cookie JWT，登录限流（技术方案 §10/§14）。"""

import bcrypt
import structlog
from domain import repositories
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.deps import COOKIE_NAME, issue_session_token, require_csrf

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = structlog.get_logger()

LOGIN_RATE_LIMIT = 5  # 每 IP 每分钟（§14）


class LoginRequest(BaseModel):
    username: str
    password: str


async def _rate_limited(request: Request) -> bool:
    ip = request.client.host if request.client else "unknown"
    key = f"login_attempts:{ip}"
    redis = request.app.state.redis
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return int(count) > LOGIN_RATE_LIMIT


@router.post("/login")
async def login(request: Request, body: LoginRequest) -> JSONResponse:
    require_csrf(request)
    settings = request.app.state.settings
    if await _rate_limited(request):
        async with request.app.state.session_factory() as session:
            await repositories.add_audit(
                session, "system", "login_rate_limited", "admin", 1, {"username": body.username}
            )
            await session.commit()
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")

    ok = bool(
        settings.admin_username
        and settings.admin_password_hash
        and body.username == settings.admin_username
        and bcrypt.checkpw(body.password.encode(), settings.admin_password_hash.encode())
    )
    async with request.app.state.session_factory() as session:
        await repositories.add_audit(
            session,
            "admin" if ok else "system",
            "login_success" if ok else "login_failed",
            "admin",
            1,
            {"username": body.username},
        )
        await session.commit()
    if not ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    response = JSONResponse({"ok": True})
    response.set_cookie(
        COOKIE_NAME,
        issue_session_token(settings),
        httponly=True,
        secure=settings.public_base_url.startswith("https"),
        samesite="lax",
        max_age=24 * 3600,
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    require_csrf(request)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
