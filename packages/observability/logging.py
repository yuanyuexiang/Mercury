"""structlog 配置：JSON 输出、trace_id 透传、敏感信息脱敏（技术方案 §14）。"""

import logging
import re
import uuid
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

# 形如 bot123456:AAxxxx 的 Telegram Bot Token（会出现在 Bot API URL 中）
_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{30,}")
# 邮箱打码：t***@example.com
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+)")
# 键名含敏感词的字段整体替换
_SECRET_KEY_RE = re.compile(r"token|secret|api_key|apikey|password|authorization", re.IGNORECASE)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        value = _BOT_TOKEN_RE.sub("bot[redacted]", value)
        value = _EMAIL_RE.sub(r"\1***\2", value)
    return value


def redact_processor(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    for key in list(event_dict):
        if _SECRET_KEY_RE.search(key):
            event_dict[key] = "[redacted]"
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def new_trace_id() -> str:
    """生成并绑定 trace_id 到当前上下文；api 中间件与 arq 任务入口调用（§14）。"""
    trace_id = uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
    return trace_id


def bind_trace_id(trace_id: str) -> None:
    """arq 任务侧绑定 api 透传过来的 trace_id，保证全链路同一 ID。"""
    structlog.contextvars.bind_contextvars(trace_id=trace_id)
