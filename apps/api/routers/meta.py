"""实例元信息（免认证）：登录页与后台品牌白标用（§20 配置面）。

只暴露品牌展示信息，绝不放任何敏感配置。
"""

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
async def meta(request: Request) -> dict[str, Any]:
    store = request.app.state.app_settings_store
    return {"brand_name": await store.brand_name()}
