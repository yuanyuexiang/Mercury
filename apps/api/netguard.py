"""api 层 SSRF 校验薄包装：把 integrations.netguard 的异常转成 HTTP 422（§14）。"""

from fastapi import HTTPException
from integrations.netguard import UnsafeUrlError, validate_public_http_url


def assert_public_http_url(url: str, allow_private: bool = False) -> None:
    try:
        validate_public_http_url(url, allow_private=allow_private)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
