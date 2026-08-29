"""SSRF 防护（技术方案 §14）：URL 校验 + 安全抓取（逐跳重定向校验、流量上限）。

api（URL 导入、供应商 base_url）与 worker（索引任务实际抓取）共用同一套规则。
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger()

MAX_FETCH_BYTES = 10 * 1024 * 1024  # §14：响应上限 10MB
MAX_REDIRECTS = 5
FETCH_TIMEOUT_S = 20.0

_REDIRECT_CODES = (301, 302, 303, 307, 308)


class UnsafeUrlError(ValueError):
    """URL 不允许访问（协议/私网/元数据地址/重定向异常/超限）。"""


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


def validate_public_http_url(url: str, allow_private: bool = False) -> None:
    """仅 http/https；DNS 解析后拒绝私网/链路本地/云元数据地址。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrlError("仅支持 http/https URL")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        raise UnsafeUrlError("域名无法解析") from exc
    for info in infos:
        if _is_private(str(info[4][0])):
            raise UnsafeUrlError("目标地址不允许（私网/元数据地址）")


def fetch_public_url(
    url: str,
    *,
    max_bytes: int = MAX_FETCH_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    timeout_s: float = FETCH_TIMEOUT_S,
) -> str:
    """安全抓取（第三轮评审修订）：关闭自动重定向，逐跳重新校验目标，限制响应大小。

    注：校验与建连之间仍有极小的 DNS rebinding 窗口；完整的解析后 IP 固定
    需要自定义 transport（含 https SNI 处理），列为 P1。当前实现已封死
    重定向绕过，并把 rebinding 窗口缩到毫秒级。
    """
    current = url
    with httpx.Client(follow_redirects=False, timeout=timeout_s) as client:
        for _ in range(max_redirects + 1):
            validate_public_http_url(current)
            with client.stream("GET", current) as resp:
                if resp.status_code in _REDIRECT_CODES:
                    location = resp.headers.get("location")
                    if not location:
                        raise UnsafeUrlError("重定向响应缺少 Location")
                    current = str(httpx.URL(current).join(location))
                    logger.info("fetch_redirect", to=current)
                    continue
                resp.raise_for_status()
                collected: list[bytes] = []
                size = 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsafeUrlError(f"响应超过 {max_bytes} 字节上限")
                    collected.append(chunk)
                encoding = resp.encoding or "utf-8"
                return b"".join(collected).decode(encoding, errors="replace")
    raise UnsafeUrlError(f"重定向超过 {max_redirects} 次")
