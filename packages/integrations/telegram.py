"""Bot API 封装（技术方案 §6 第 4 步）：发送消息、通知运营者。

实现 domain.orchestrator.MessageSender 协议（结构化类型，无需继承）。
"""

import structlog
from aiogram import Bot

logger = structlog.get_logger()


class AiogramSender:
    def __init__(self, token: str, operator_chat_id: str = "") -> None:
        self._bot = Bot(token=token)
        self._operator_chat_id = operator_chat_id

    async def send_message(self, chat_id: int, text: str) -> int:
        message = await self._bot.send_message(chat_id, text)
        return message.message_id

    async def notify_operator(self, text: str) -> None:
        """尽力而为：通知失败只记日志，绝不阻塞主管线。"""
        if not self._operator_chat_id:
            return
        try:
            await self._bot.send_message(int(self._operator_chat_id), text)
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
