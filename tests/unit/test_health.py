"""M1 冒烟：/health/live 不依赖任何基础设施即可响应。"""

import httpx
from api.main import create_app


async def test_health_live() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
