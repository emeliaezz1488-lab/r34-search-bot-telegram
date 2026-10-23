import time
import re
import logging
from typing import Tuple
from aiogram import Router, types, F
from aiogram.enums import ChatType, ChatMemberStatus, ChatAction
import config
from database import db
from utils.filters import FlexibleCommand
from utils.antispam import antispam
from utils.media import send_posts, send_pixiv_manga
from utils.task_tracker import TrackChatTask
from services.rule34 import rule34_service
from services.danbooru import danbooru_service
from services.pixiv import pixiv_service
from services.konachan import konachan_service
from services.pornhub import pornhub_service

logger = logging.getLogger("commands")

router = Router(name="commands")

# Защита от двойного приветствия при добавлении в группу
_last_greeted_at = {}

def should_greet(chat_id: int) -> bool:
    now = time.time()
    last = _last_greeted_at.get(chat_id, 0)
    if now - last < 30:
        return False
    _last_greeted_at[chat_id] = now
    return True

def get_welcome_text() -> str:
    return (
        "👋 <b>Всем привет! Я NSFW Searcher Bot.</b>\n\n"
        "Я умею находить и отправлять арты, видео и мангу с Rule34, Danbooru, Pixiv, Konachan и Pornhub прямо в этом чате!\n\n"
        "⚠️ <b>ВАЖНО:</b> Теги для поиска пишите <u>ТОЛЬКО на английском языке</u> "
        "(например: <code>futa</code>, <code>femboy</code>, <code>anime</code>, <code>1girl</code>, <code>catgirls</code> и т.д.)! "
        "На русском языке сайты ничего не найдут.\n\n"
        "🔥 <b>Команды (через слэш /):</b>\n"
        "• <code>/r34 [теги] [кол-во]</code> — поиск на Rule34 (до 10 постов)\n"
        "• <code>/danbooru [теги] [кол-во]</code> — поиск на Danbooru\n"
        "• <code>/konachan [теги] [кол-во]</code> — поиск на Konachan (аниме арты & хентай)\n"
        "• <code>/ph [запрос] [кол-во]</code> — поиск видео на Pornhub\n"
        "• <code>/pixiv [теги] [кол-во]</code> — поиск на Pixiv (SFW)\n"
        "• <code>/pixivnsfw [теги] [кол-во]</code> — поиск на Pixiv R-18\n"
        "• <code>/pixivmanga [теги]</code> — сборка и отправка R-18 манги альбомом\n"
        "• <code>/settings</code> — панель настроек для этого чата (спойлеры, автоудаление, триггеры)\n"
        "• <code>/admin</code> — панель администратора бота (для админов)\n\n"
        "⚡ <b>Все триггеры в чате (работают в тексте без слэша):</b>\n"
        "• <code>фута</code> — поиск арта по тегу futa\n"
        "• <code>фембой</code> — поиск арта по тегу femboy\n"
        "• <code>фута + фембой</code> (или <code>фута+фембой</code>) — видео по тегам futa femboy\n"
        "• <code>порно</code> — случайное NSFW видео\n"
        "• <code>r34 [теги] [кол-во]</code> — быстрый поиск на Rule34\n"
        "• <code>konachan [теги] [кол-во]</code> — быстрый поиск на Konachan\n"
        "• <code>ph [запрос] [кол-во]</code> — быстрый поиск на Pornhub\n"
        "• <code>pixiv [теги] [кол-во]</code> — быстрый поиск на Pixiv\n"
        "• <code>pixivnsfw [теги] [кол-во]</code> — быстрый поиск на Pixiv R-18\n"
        "• <code>pixivmanga [теги]</code> — поиск и отправка манги с Pixiv\n"
        "• <code>связь</code> — 📞Великая связь!\n"
        "• <code>maymay</code> — секретное фото\n"
        "• <code>semor</code> — фото axiom"
    )

from utils.filters import FlexibleCommand, smart_parse_tags_and_count
from utils.antidaun import antidaun, TrackUserTask

def parse_tags_and_count(args: str, chat_id: int, user_id: int = 0) -> Tuple[str, int]:
    return smart_parse_tags_and_count(args, chat_id, user_id)

# Приветствие при добавлении бота в группу через my_chat_member
@router.my_chat_member()
async def on_bot_added_chat_member(event: types.ChatMemberUpdated):
    logger.debug(f"[EVENT:my_chat_member] Chat: {event.chat.id} ({event.chat.title}) | Old: {event.old_chat_member.status} -> New: {event.new_chat_member.status}")
    if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        db.record_chat(
            event.chat.id,
            event.chat.title or "Группа",
            str(event.chat.type)
        )
        was_member = event.old_chat_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)
        is_member = event.new_chat_member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)

        if not was_member and is_member:
            if should_greet(event.chat.id):
                logger.info(f"👋 Отправка приветствия в чат {event.chat.id} ({event.chat.title})")
                try:
                    await event.bot.send_message(chat_id=event.chat.id, text=get_welcome_text(), parse_mode="HTML")
                except Exception as e:
                    logger.error(f"[Greeting] Failed to send welcome message: {e}")

# Приветствие через сервисное сообщение new_chat_members
@router.message(F.new_chat_members)
async def on_bot_added_service_message(message: types.Message):
    for member in message.new_chat_members:
        if member.id == message.bot.id:
            logger.debug(f"[EVENT:new_chat_members] Bot added to chat {message.chat.id} ({message.chat.title})")
            db.record_chat(
                message.chat.id,
                message.chat.title or "Группа",
                str(message.chat.type)
            )
            try:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text=get_welcome_text(),
                    parse_mode="HTML"
                )
                logger.info(f"✅ Отправлено приветствие в группу: {message.chat.title} ({message.chat.id})")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки приветствия в группу {message.chat.id}: {e}")

# Команды /start и /help
@router.message(FlexibleCommand("start", "help"))
async def cmd_start_help(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id}")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )
    await message.reply(get_welcome_text(), parse_mode="HTML")

@router.message(FlexibleCommand("r34"))
async def cmd_r34(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    if not cmd_args:
        await message.reply(
            "❌ Использование: <code>/r34 [теги] [кол-во]</code>\n"
            "Пример: <code>/r34 anime 2</code>\n"
            "<i>⚠️ ВАЖНО: Теги пишите только на английском языке!</i>",
            parse_mode="HTML"
        )
        return

    can_proceed, wait_time = antidaun.check_rate_limit(user_id)
    if not can_proceed:
        await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    antidaun.record_request(user_id)

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            tags, count, media_filter = parse_tags_and_count(cmd_args, chat_id, user_id)
            antiai = config.is_antiai(chat_id)
            t_search = time.time()
            logger.info(f"🔍 [Search:Rule34] Поиск по тегам '{tags}' (запрошено: {count} шт, antiai={antiai}, filter={media_filter})...")
            posts = await rule34_service.search(tags, limit=config.POSTS_COUNT, antiai=antiai)
            logger.info(f"✅ [Search:Rule34] Найдено {len(posts)} постов за {time.time() - t_search:.2f}с")

            if not posts:
                await message.reply("Ничего не найдено! (Убедитесь, что теги написаны на английском языке)")
                return

            sent = await send_posts(
                bot=message.bot,
                chat_id=chat_id,
                posts=posts,
                requested_tags=tags,
                count=count,
                reply_to_message_id=message.message_id,
                media_filter=media_filter
            )
            if sent == 0:
                await message.reply("❌ Не удалось отправить медиа (возможно, файл слишком большой или недоступен).")

@router.message(FlexibleCommand("danbooru"))
async def cmd_danbooru(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    if not cmd_args:
        await message.reply(
            "❌ Использование: <code>/danbooru [теги] [кол-во]</code>\n"
            "Пример: <code>/danbooru anime 2</code>\n"
            "<i>⚠️ ВАЖНО: Теги пишите только на английском языке!</i>",
            parse_mode="HTML"
        )
        return

    can_proceed, wait_time = antidaun.check_rate_limit(user_id)
    if not can_proceed:
        await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    antidaun.record_request(user_id)

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            tags, count, media_filter = parse_tags_and_count(cmd_args, chat_id, user_id)
            t_search = time.time()
            logger.info(f"🔍 [Search:Danbooru] Поиск по тегам '{tags}' (запрошено: {count} шт, filter={media_filter})...")
            posts = await danbooru_service.search(tags, limit=config.POSTS_COUNT)
            logger.info(f"✅ [Search:Danbooru] Найдено {len(posts)} постов за {time.time() - t_search:.2f}с")

            if not posts:
                await message.reply("Ничего не найдено на Danbooru!")
                return

            sent = await send_posts(
                bot=message.bot,
                chat_id=chat_id,
                posts=posts,
                requested_tags=tags,
                count=count,
                reply_to_message_id=message.message_id,
                media_filter=media_filter
            )
            if sent == 0:
                await message.reply("❌ Не удалось отправить медиа с Danbooru.")

@router.message(FlexibleCommand("konachan"))
async def cmd_konachan(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    can_proceed, wait_time = antidaun.check_rate_limit(user_id)
    if not can_proceed:
        await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    antidaun.record_request(user_id)

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            tags, count, media_filter = parse_tags_and_count(cmd_args, chat_id, user_id)
            t_search = time.time()
            logger.info(f"🔍 [Search:Konachan] Поиск по тегам '{tags}' (запрошено: {count} шт, filter={media_filter})...")
            posts = await konachan_service.search(tags, limit=config.POSTS_COUNT)
            logger.info(f"✅ [Search:Konachan] Найдено {len(posts)} постов за {time.time() - t_search:.2f}с")

            if not posts:
                await message.reply("Ничего не найдено на Konachan! (Попробуйте другие теги)")
                return

            sent = await send_posts(
                bot=message.bot,
                chat_id=chat_id,
                posts=posts,
                requested_tags=tags,
                count=count,
                reply_to_message_id=message.message_id,
                media_filter=media_filter
            )
            if sent == 0:
                await message.reply("❌ Не удалось отправить медиа с Konachan.")

@router.message(FlexibleCommand("ph", "pornhub", "порнхаб"))
async def cmd_pornhub(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    can_proceed, wait_time = antidaun.check_rate_limit(user_id)
    if not can_proceed:
        await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    antidaun.record_request(user_id)

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            tags, count, media_filter = parse_tags_and_count(cmd_args, chat_id, user_id)
            t_search = time.time()
            logger.info(f"🔍 [Search:Pornhub] Поиск по запросу '{tags}' (запрошено: {count} шт)...")
            posts = await pornhub_service.search(tags, limit=count * 3)
            logger.info(f"✅ [Search:Pornhub] Найдено {len(posts)} видео за {time.time() - t_search:.2f}с")

            if not posts:
                await message.reply("Ничего не найдено на Pornhub! (Попробуйте изменить запрос на английском)")
                return

            sent = await send_posts(
                bot=message.bot,
                chat_id=chat_id,
                posts=posts,
                requested_tags=tags,
                count=count,
                reply_to_message_id=message.message_id,
                media_filter=media_filter
            )
            if sent == 0:
                await message.reply("❌ Не удалось отправить медиа с Pornhub.")

@router.message(FlexibleCommand("pixiv"))
async def cmd_pixiv(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if not pixiv_service.get_refresh_token():
        await message.reply("Pixiv: укажи refresh_token в .env файле (PIXIV_REFRESH_TOKEN).")
        return

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    if not cmd_args:
        await message.reply(
            "❌ Использование: <code>/pixiv [теги] [кол-во]</code>\n"
            "Пример: <code>/pixiv 1girl 2</code>\n"
            "<i>⚠️ ВАЖНО: Теги пишите только на английском языке!</i>",
            parse_mode="HTML"
        )
        return

    can_proceed, wait_time = antidaun.check_rate_limit(user_id)
    if not can_proceed:
        await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    antidaun.record_request(user_id)

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            tags, count, media_filter = parse_tags_and_count(cmd_args, chat_id, user_id)
            t_search = time.time()
            logger.info(f"🔍 [Search:Pixiv] Поиск по тегам '{tags}' (запрошено: {count} шт, filter={media_filter})...")
            posts = await pixiv_service.search(tags, limit=count * 3, r18_only=False)
            logger.info(f"✅ [Search:Pixiv] Найдено {len(posts)} постов за {time.time() - t_search:.2f}с")

            if not posts:
                if pixiv_service.last_error:
                    await message.reply(f"⚠️ <b>Ошибка Pixiv:</b> <code>{pixiv_service.last_error}</code>\n<i>Проверьте PIXIV_REFRESH_TOKEN или попробуйте позже.</i>", parse_mode="HTML")
                else:
                    await message.reply("Ничего не найдено на Pixiv! (Попробуйте другие теги на английском)")
                return

            sent = await send_posts(
                bot=message.bot,
                chat_id=chat_id,
                posts=posts,
                requested_tags=tags,
                count=count,
                reply_to_message_id=message.message_id,
                media_filter=media_filter
            )
            if sent == 0:
                await message.reply("❌ Не удалось отправить арт с Pixiv (ошибка загрузки медиа).")

@router.message(FlexibleCommand("pixivnsfw"))
async def cmd_pixivnsfw(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if not pixiv_service.get_refresh_token():
        await message.reply("Pixiv: укажи refresh_token в .env файле (PIXIV_REFRESH_TOKEN).")
        return

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    if not cmd_args:
        await message.reply(
            "❌ Использование: <code>/pixivnsfw [теги] [кол-во]</code>\n"
            "Пример: <code>/pixivnsfw femboy 2</code>\n"
            "<i>⚠️ ВАЖНО: Теги пишите только на английском языке!</i>",
            parse_mode="HTML"
        )
        return

    can_proceed, wait_time = antidaun.check_rate_limit(user_id)
    if not can_proceed:
        await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    antidaun.record_request(user_id)

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            tags, count, media_filter = parse_tags_and_count(cmd_args, chat_id, user_id)
            t_search = time.time()
            logger.info(f"🔍 [Search:Pixiv R-18] Поиск по тегам '{tags}' (запрошено: {count} шт, filter={media_filter})...")
            posts = await pixiv_service.search(tags, limit=count * 3, r18_only=True)
            logger.info(f"✅ [Search:Pixiv R-18] Найдено {len(posts)} постов за {time.time() - t_search:.2f}с")

            if not posts:
                if pixiv_service.last_error:
                    await message.reply(f"⚠️ <b>Ошибка Pixiv R-18:</b> <code>{pixiv_service.last_error}</code>\n<i>Проверьте PIXIV_REFRESH_TOKEN или попробуйте позже.</i>", parse_mode="HTML")
                else:
                    await message.reply("Ничего не найдено на Pixiv R-18! (Попробуйте другие теги на английском)")
                return

            sent = await send_posts(
                bot=message.bot,
                chat_id=chat_id,
                posts=posts,
                requested_tags=tags,
                count=count,
                reply_to_message_id=message.message_id,
                media_filter=media_filter
            )
            if sent == 0:
                await message.reply("❌ Не удалось отправить арт с Pixiv R-18 (ошибка загрузки медиа).")

@router.message(FlexibleCommand("pixivmanga"))
async def cmd_pixivmanga(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/{cmd_name}] User: {user_id} | Chat: {chat_id} | Args: '{cmd_args}'")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if not pixiv_service.get_refresh_token():
        await message.reply("Pixiv: укажи refresh_token в .env файле (PIXIV_REFRESH_TOKEN).")
        return

    if await antispam.is_spam(user_id, chat_id):
        logger.warning(f"🚫 Анти-спам сработал на user {user_id} в {chat_id}")
        return

    tags = cmd_args.strip()
    if not tags:
        await message.reply(
            "❌ Использование: <code>/pixivmanga [теги]</code>\n"
            "Пример: <code>/pixivmanga futanari</code>\n"
            "<i>⚠️ ВАЖНО: Теги пишите только на английском языке!</i>",
            parse_mode="HTML"
        )
        return

    if not await antidaun.can_start(user_id):
        await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
        return

    async with TrackUserTask(user_id):
        async with TrackChatTask(chat_id):
            await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
            logger.debug(f"[PixivManga] Fetching manga for '{tags}'")
            status_msg = await message.reply("⏳ Загружаем мангу Pixiv R-18...")
            success = await send_pixiv_manga(
                bot=message.bot,
                chat_id=chat_id,
                tags=tags,
                reply_to_message_id=message.message_id
            )
            try:
                await status_msg.delete()
            except Exception:
                pass

            if not success:
                logger.warning(f"[PixivManga] Не удалось собрать мангу для '{tags}'")
                err_text = f" (ошибка: <code>{pixiv_service.last_error}</code>)" if pixiv_service.last_error else ""
                await message.reply(f"Ничего не найдено или не удалось собрать мангу!{err_text}", parse_mode="HTML")
            else:
                logger.info(f"[PixivManga] Альбом манги успешно отправлен в {chat_id}")

@router.message(FlexibleCommand("pixivcheck"))
async def cmd_pixivcheck(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    """Диагностика подключения и работоспособности Pixiv API."""
    user_id = message.from_user.id if message.from_user else 0
    token = pixiv_service.get_refresh_token()
    if not token:
        await message.reply("❌ <b>PIXIV_REFRESH_TOKEN отсутствует</b> в .env или базе данных.", parse_mode="HTML")
        return

    status_msg = await message.reply("🔍 <b>Диагностика Pixiv...</b>\n1. Проверка авторизации...", parse_mode="HTML")
    t0 = time.time()

    # Шаг 1: Авторизация
    try:
        api = await asyncio.to_thread(pixiv_service._ensure_api_sync, True)
        auth_dur = time.time() - t0
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Ошибка авторизации Pixiv:</b>\n<code>{e}</code>\n\nТокен устарел или заблокирован сервером.", parse_mode="HTML")
        return

    # Шаг 2: Тестовый поиск
    await status_msg.edit_text(f"🔍 <b>Диагностика Pixiv...</b>\n✅ Авторизация успешна ({auth_dur:.2f}с)\n2. Тестовый поиск...", parse_mode="HTML")
    t1 = time.time()
    posts = await pixiv_service.search("1girl", limit=1, r18_only=False)
    search_dur = time.time() - t1

    if not posts:
        err = pixiv_service.last_error or "Пустой ответ"
        await status_msg.edit_text(f"❌ <b>Поиск не вернул результатов:</b> <code>{err}</code>", parse_mode="HTML")
        return

    # Шаг 3: Скачивание тестового арта
    await status_msg.edit_text(f"🔍 <b>Диагностика Pixiv...</b>\n✅ Авторизация ({auth_dur:.2f}с)\n✅ Поиск найден арт #{posts[0]['id']} ({search_dur:.2f}с)\n3. Скачивание тестового арта...", parse_mode="HTML")
    t2 = time.time()
    img_bytes = await pixiv_service.download_image(posts[0]["file_url"])
    dl_dur = time.time() - t2

    if not img_bytes:
        await status_msg.edit_text("❌ <b>Ошибка скачивания:</b> Pixiv CDN (i.pximg.net) вернул 0 байт или заблокировал запрос.", parse_mode="HTML")
        return

    size_kb = len(img_bytes) / 1024
    await status_msg.edit_text(
        f"✅ <b>Pixiv полностью работает!</b>\n\n"
        f"• Авторизация: <code>{auth_dur:.2f}с</code>\n"
        f"• Поиск: <code>{search_dur:.2f}с</code> (ID #{posts[0]['id']})\n"
        f"• Скачивание CDN: <code>{dl_dur:.2f}с</code> ({size_kb:.1f} KB)\n"
        f"• Токен: <code>{token[:6]}...{token[-4:]}</code>",
        parse_mode="HTML"
    )
