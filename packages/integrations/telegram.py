"""Bot API 封装（技术方案 §6 第 4 步）：发送消息、通知运营者。

实现 domain.orchestrator.MessageSender 协议（结构化类型，无需继承）。
"""

from typing import Protocol

import structlog
from aiogram import Bot

logger = structlog.get_logger()


class AiogramSender:
    def __init__(self, token: str, operator_chat_id: str = "") -> None:
        self._bot = Bot(token=token)
        self.operator_chat_id = operator_chat_id

    async def send_message(self, chat_id: int, text: str) -> int:
        message = await self._bot.send_message(chat_id, text)
        return message.message_id

    async def notify_operator(self, text: str) -> None:
        """尽力而为：通知失败只记日志，绝不阻塞主管线。"""
        if not self.operator_chat_id:
            return
        try:
            await self._bot.send_message(int(self.operator_chat_id), text)
        except Exception:
            logger.warning("operator_notify_failed")

    async def close(self) -> None:
        await self._bot.session.close()


class LoggingSender:
    """无 TELEGRAM_BOT_TOKEN 时的本地开发替身：只打日志，不发网络请求。"""

    def __init__(self) -> None:
        self._next_id = 1

    async def send_message(self, chat_id: int, text: str) -> int:
        logger.info("send_message_stub", chat_id=chat_id, text=text)
        self._next_id += 1
        return self._next_id

    async def notify_operator(self, text: str) -> None:
        logger.info("notify_operator_stub", text=text)

    async def close(self) -> None:
        return None


def build_sender(token: str, operator_chat_id: str = "") -> AiogramSender | LoggingSender:
    if token:
        return AiogramSender(token, operator_chat_id)
    logger.warning("telegram_token_missing_using_logging_sender")
    return LoggingSender()


class DynamicSender:
    """后台可配 Telegram（migration 0007）：每次发送前解析当前 token/chat_id。

    token 变化时重建内部 AiogramSender（关闭旧连接）；无 token 时退化为 LoggingSender
    行为。解析走 AppSettingsStore（DB 优先 env 兜底，60s 缓存 + 广播失效），
    后台保存新 token 后无需重启即生效——与 DynamicChatClient 同一模式（§12）。
    """

    def __init__(self, store: "SettingsResolver") -> None:
        self._store = store
        self._active_token = ""
        self._inner: AiogramSender | LoggingSender = LoggingSender()

    async def _resolve(self) -> AiogramSender | LoggingSender:
        token = await self._store.telegram_bot_token()
        chat_id = await self._store.operator_chat_id()
        if token != self._active_token:
            await self._inner.close()
            self._inner = AiogramSender(token, chat_id) if token else LoggingSender()
            self._active_token = token
            logger.info("telegram_sender_rebuilt", configured=bool(token))
        elif isinstance(self._inner, AiogramSender):
            self._inner.operator_chat_id = chat_id  # chat_id 变化无需重建连接
        return self._inner

    async def send_message(self, chat_id: int, text: str) -> int:
        return await (await self._resolve()).send_message(chat_id, text)

    async def notify_operator(self, text: str) -> None:
        await (await self._resolve()).notify_operator(text)

    async def close(self) -> None:
        await self._inner.close()


class SettingsResolver(Protocol):
    async def telegram_bot_token(self) -> str: ...

    async def operator_chat_id(self) -> str: ...


async def probe_token(token: str) -> str:
    """验证 bot token 有效性，返回 bot username（后台保存前调用）。"""
    bot = Bot(token=token)
    try:
        me = await bot.get_me()
        return me.username or str(me.id)
    finally:
        await bot.session.close()


async def register_webhook(token: str, public_base_url: str, webhook_secret: str) -> None:
    """注册 webhook（§5 双重校验：URL 路径 secret + secret_token 头）。"""
    bot = Bot(token=token)
    try:
        await bot.set_webhook(
            f"{public_base_url}/webhooks/telegram/{webhook_secret}",
            secret_token=webhook_secret,
            allowed_updates=["message"],
        )
    finally:
        await bot.session.close()
