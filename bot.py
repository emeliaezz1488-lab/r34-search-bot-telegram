import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import config
from database import db
from handlers.admin import router as admin_router
from handlers.settings import router as settings_router
from handlers.commands import router as commands_router
from handlers.triggers import router as triggers_router
from services.pixiv import pixiv_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("NSFWBot")

async def pixiv_keepalive_loop():
    """Фоновое авто-обновление access_token Pixiv каждые ~45 минут."""
    while True:
        try:
            await asyncio.sleep(pixiv_service.access_ttl)
            if pixiv_service.get_refresh_token():
                await asyncio.to_thread(pixiv_service._ensure_api_sync, True)
                logger.info("[Pixiv] access_token успешно обновлен в фоне.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Pixiv] Ошибка фонового обновления токена: {e}")

async def main():
    if not config.BOT_TOKEN:
        logger.error(
            "\n"
            "===============================================================\n"
            " ОШИБКА: BOT_TOKEN не указан!\n"
            " Открой файл .env в папке бота и вставь токен от @BotFather:\n"
            " BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ\n"
            "===============================================================\n"
        )
        return

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Регистрация роутеров
    dp.include_router(admin_router)
    dp.include_router(settings_router)
    dp.include_router(commands_router)
    dp.include_router(triggers_router)

    # Фоновая задача Pixiv keepalive
    keepalive_task = asyncio.create_task(pixiv_keepalive_loop())

    logger.info("Запуск NSFW Telegram Bot...")
    try:
        # Сброс старых висящих обновлений
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        keepalive_task.cancel()
        await bot.session.close()
        logger.info("Бот остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Выход по сигналу пользователя.")
