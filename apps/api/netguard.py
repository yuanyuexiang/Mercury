"""SSRF 防护（技术方案 §14）：URL 导入与后台配置的 LLM base_url 共用。"""

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException


def _is_private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def assert_public_http_url(url: str, allow_private: bool = False) -> None:
    """仅 http/https；DNS 解析后拒绝私网/链路本地/云元数据地址（重定向由 httpx 关闭跟随另查）。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="仅支持 http/https URL")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise HTTPException(status_code=422, detail="域名无法解析") from exc
    for info in infos:
        ip = info[4][0]
        if _is_private(str(ip)):
            raise HTTPException(status_code=422, detail="目标地址不允许（私网/元数据地址）")
