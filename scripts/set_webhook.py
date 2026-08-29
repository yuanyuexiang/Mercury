"""注册 Telegram webhook（技术方案 §5）：URL 路径 secret + secret_token 头双重校验。

用法：确保 .env 已配置 TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET / PUBLIC_BASE_URL，
然后 uv run python scripts/set_webhook.py
"""

import asyncio

from aiogram import Bot
from domain.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("缺少 TELEGRAM_BOT_TOKEN")
    if not settings.telegram_webhook_secret or not settings.public_base_url:
        raise SystemExit("缺少 TELEGRAM_WEBHOOK_SECRET 或 PUBLIC_BASE_URL")

    url = f"{settings.public_base_url}/webhooks/telegram/{settings.telegram_webhook_secret}"
    bot = Bot(token=settings.telegram_bot_token)
    try:
        await bot.set_webhook(
            url,
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=["message"],
        )
        info = await bot.get_webhook_info()
        print(f"webhook 已设置：{info.url}（pending: {info.pending_update_count}）")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
