import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher, BaseMiddleware, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat
)
import config
from database import db
from handlers.admin import router as admin_router
from handlers.settings import router as settings_router
from handlers.commands import router as commands_router
from handlers.triggers import router as triggers_router
from services.pixiv import pixiv_service
from utils.http_client import close_http_session

# Настройка чистого информативного логирования в консоль
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Приглушаем шумные внутренние логгеры aiohttp/asyncio
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)

logger = logging.getLogger("NSFWBot")

async def setup_bot_commands(bot: Bot):
    """
    Регистрация команд бота в меню подсказок Telegram через официальное API (setMyCommands).
    Теперь при вводе '/' в любом чате или группе Telegram сразу покажет этого бота и его команды!
    """
    base_commands = [
        BotCommand(command="r34", description="Поиск на Rule34 (арты и видео)"),
        BotCommand(command="danbooru", description="Поиск на Danbooru"),
        BotCommand(command="konachan", description="Поиск артов на Konachan"),
        BotCommand(command="ph", description="Поиск видео на Pornhub"),
        BotCommand(command="pixiv", description="Поиск безопасных артов на Pixiv"),
        BotCommand(command="pixivnsfw", description="Поиск R-18 артов на Pixiv"),
        BotCommand(command="pixivmanga", description="Сборка R-18 манги альбомом"),
        BotCommand(command="settings", description="Панель настроек бота в этом чате"),
        BotCommand(command="admin", description="🛡 Панель администратора бота"),
        BotCommand(command="help", description="Список команд и всех триггеров"),
    ]

    try:
        # Для личных сообщений
        await bot.set_my_commands(base_commands, scope=BotCommandScopeAllPrivateChats())
        # Для всех групп и супергрупп
        await bot.set_my_commands(base_commands, scope=BotCommandScopeAllGroupChats())
        # По умолчанию
        await bot.set_my_commands(base_commands, scope=BotCommandScopeDefault())
        logger.info("✅ Команды бота успешно зарегистрированы во всех группах и чатах!")
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации команд setMyCommands: {e}")

    # Персональное меню для всех администраторов
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(base_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            logger.info(f"✅ Персональные команды админа зарегистрированы для ID: {admin_id}")
        except Exception as e:
            logger.warning(f"Не удалось установить команды для админа {admin_id}: {e}")

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

async def broadcast_status(bot: Bot, text: str):
    """
    Рассылка статуса бота (запуск / отключение) во все известные чаты и беседы.
    """
    chats = db.get_known_chats()
    if not chats:
        return
    logger.info(f"📢 Рассылка статуса ({len(chats)} чатов): {text}")
    for chat in chats:
        chat_id = chat.get("id")
        if not chat_id or db.is_blacklisted(chat_id):
            continue
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            await asyncio.sleep(0.05)  # Предотвращение FloodWait
        except Exception as e:
            logger.debug(f"[Broadcast] Не удалось отправить в чат {chat_id} ({chat.get('title')}): {e}")

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

    # Получаем информацию о боте
    me = await bot.get_me()
    logger.info(f"🤖 Авторизован как @{me.username} (ID: {me.id}, Name: {me.full_name})")

    # Регистрируем команды в Telegram API
    await setup_bot_commands(bot)

    # Фоновая задача Pixiv keepalive
    keepalive_task = asyncio.create_task(pixiv_keepalive_loop())

    print(
        "\n"
        "========================================================================\n"
        f" 🚀 NSFW Telegram Bot запущен: @{me.username}\n"
        "------------------------------------------------------------------------\n"
        " 💡 ВАЖНАЯ ИНФОРМАЦИЯ ДЛЯ ТРИГГЕРОВ В ГРУППАХ ('фута', 'фембой', 'порно'):\n"
        " В Telegram у всех ботов по умолчанию включен 'Group Privacy Mode'.\n"
        " Из-за этого Telegram НЕ присылает боту обычный текст в беседах!\n\n"
        " Чтобы бот слышал ВСЕ слова-триггеры без слэша в группах:\n"
        " 1. Зайди в Telegram к боту @BotFather\n"
        " 2. Отправь команду: /setprivacy\n"
        " 3. Выбери своего бота\n"
        " 4. Нажми: Disable\n"
        " 5. Передобавь бота в группу (или сделай администратором с правом читать сообщения)\n"
        "========================================================================\n"
    )

    try:
        # Сброс старых висящих обновлений
        await bot.delete_webhook(drop_pending_updates=True)
        # Оповещение о запуске во все чаты
        await broadcast_status(bot, "🟢 <b>Бот снова в сети!</b>")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        # Оповещение об отключении во все чаты
        try:
            await asyncio.shield(broadcast_status(bot, "🔴 <b>Бот отключается и уходит на тех перерыв.</b>"))
        except BaseException as e:
            logger.debug(f"Исключение при отправке оповещения об отключении: {e}")

        keepalive_task.cancel()
        await close_http_session()
        await bot.session.close()
        logger.info("Бот остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Выход по сигналу пользователя.")
