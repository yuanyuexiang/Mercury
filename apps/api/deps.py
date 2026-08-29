"""FastAPI 依赖注入：设置、引擎、Redis；M8 加当前管理员（cookie JWT）。"""

from domain.config import Settings
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> AsyncEngine:
    return request.app.state.engine


def get_redis(request: Request) -> Redis:
    return request.app.state.redis
