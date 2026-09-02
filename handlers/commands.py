import time
import re
import logging
from typing import Tuple
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.enums import ChatType, ChatMemberStatus
import config
from database import db
from utils.antispam import antispam
from utils.media import send_posts, send_pixiv_manga
from utils.task_tracker import TrackChatTask
from services.rule34 import rule34_service
from services.danbooru import danbooru_service
from services.pixiv import pixiv_service

logger = logging.getLogger(__name__)

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
        "Я умею находить и отправлять арты, видео и мангу с Rule34, Danbooru и Pixiv прямо в этом чате!\n\n"
        "⚠️ <b>ВАЖНО:</b> Теги для поиска пишите <u>ТОЛЬКО на английском языке</u> "
        "(например: <code>futa</code>, <code>femboy</code>, <code>anime</code>, <code>1girl</code>, <code>catgirls</code> и т.д.)! "
        "На русском языке сайты ничего не найдут.\n\n"
        "🔥 <b>Команды (через слэш /):</b>\n"
        "• <code>/r34 [теги] [кол-во]</code> — поиск на Rule34 (до 10 постов)\n"
        "• <code>/danbooru [теги] [кол-во]</code> — поиск на Danbooru\n"
        "• <code>/pixiv [теги] [кол-во]</code> — поиск на Pixiv (SFW)\n"
        "• <code>/pixivnsfw [теги] [кол-во]</code> — поиск на Pixiv R-18\n"
        "• <code>/pixivmanga [теги]</code> — сборка и отправка R-18 манги альбомом\n"
        "• <code>/settings</code> — панель настроек для этого чата (спойлеры, автоудаление, триггеры)\n\n"
        "⚡ <b>Все триггеры в чате (работают в тексте без слэша):</b>\n"
        "• <code>фута</code> — поиск арта по тегу futa\n"
        "• <code>фембой</code> — поиск арта по тегу femboy\n"
        "• <code>фута + фембой</code> (или <code>фута+фембой</code>) — видео по тегам futa femboy\n"
        "• <code>порно</code> — случайное NSFW видео\n"
        "• <code>r34 [теги] [кол-во]</code> — быстрый поиск на Rule34\n"
        "• <code>pixiv [теги] [кол-во]</code> — быстрый поиск на Pixiv\n"
        "• <code>pixivnsfw [теги] [кол-во]</code> — быстрый поиск на Pixiv R-18\n"
        "• <code>pixivmanga [теги]</code> — быстрый поиск манги на Pixiv"
    )

def parse_tags_and_count(args: str, chat_id: int) -> Tuple[str, int]:
    args = (args or "").strip()
    default_count = config.get_send_count(chat_id)
    if not args:
        return "", default_count

    parts = args.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        tags = parts[0]
        count = min(int(parts[1]), 10)
    else:
        tags = args
        count = default_count
    return tags, count

# Приветствие при добавлении бота в группу через my_chat_member
@router.my_chat_member()
async def on_bot_added_chat_member(event: types.ChatMemberUpdated):
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
                try:
                    await event.bot.send_message(chat_id=event.chat.id, text=get_welcome_text(), parse_mode="HTML")
                except Exception as e:
                    logger.error(f"[Greeting] Failed to send welcome message: {e}")

# Приветствие через сервисное сообщение new_chat_members
@router.message(F.new_chat_members)
async def on_bot_added_service_message(message: types.Message):
    for member in message.new_chat_members:
        if member.id == message.bot.id:
            db.record_chat(
                message.chat.id,
                message.chat.title or "Группа",
                str(message.chat.type)
            )
            if should_greet(message.chat.id):
                try:
                    await message.reply(get_welcome_text(), parse_mode="HTML")
                except Exception as e:
                    logger.error(f"[Greeting] Failed to send reply greeting: {e}")
            break

@router.message(Command("start", "help"))
async def cmd_start_help(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if db.is_blacklisted(user_id) or db.is_blacklisted(message.chat.id):
        return

    db.record_chat(
        message.chat.id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )
    await message.reply(get_welcome_text(), parse_mode="HTML")

@router.message(Command("r34"))
async def cmd_r34(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if db.is_blacklisted(user_id) or db.is_blacklisted(message.chat.id):
        return

    db.record_chat(
        message.chat.id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if await antispam.is_spam(user_id, message.chat.id):
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    if not raw_args:
        await message.reply("❌ Использование: <code>/r34 [теги] [кол-во]</code>\nПример: <code>/r34 anime 2</code>\n<i>⚠️ Теги пишите только на английском!</i>", parse_mode="HTML")
        return

    async with TrackChatTask(message.chat.id):
        tags, count = parse_tags_and_count(raw_args, message.chat.id)
        posts = await rule34_service.search(tags, limit=config.POSTS_COUNT, antiai=config.is_antiai(message.chat.id))
        if not posts:
            await message.reply("Ничего не найдено! (Проверьте правильность написания тегов на английском)")
            return

        sent = await send_posts(
            bot=message.bot,
            chat_id=message.chat.id,
            posts=posts,
            requested_tags=tags,
            count=count,
            reply_to_message_id=message.message_id
        )
        if sent == 0:
            await message.reply("❌ Не удалось отправить медиа (возможно, файл слишком большой или недоступен).")

@router.message(Command("danbooru"))
async def cmd_danbooru(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if db.is_blacklisted(user_id) or db.is_blacklisted(message.chat.id):
        return

    db.record_chat(
        message.chat.id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if await antispam.is_spam(user_id, message.chat.id):
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    if not raw_args:
        await message.reply("❌ Использование: <code>/danbooru [теги] [кол-во]</code>\nПример: <code>/danbooru anime 2</code>\n<i>⚠️ Теги пишите только на английском!</i>", parse_mode="HTML")
        return

    async with TrackChatTask(message.chat.id):
        tags, count = parse_tags_and_count(raw_args, message.chat.id)
        posts = await danbooru_service.search(tags, limit=config.POSTS_COUNT)
        if not posts:
            await message.reply("Ничего не найдено на Danbooru!")
            return

        sent = await send_posts(
            bot=message.bot,
            chat_id=message.chat.id,
            posts=posts,
            requested_tags=tags,
            count=count,
            reply_to_message_id=message.message_id
        )
        if sent == 0:
            await message.reply("❌ Не удалось отправить медиа с Danbooru.")

@router.message(Command("pixiv"))
async def cmd_pixiv(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if db.is_blacklisted(user_id) or db.is_blacklisted(message.chat.id):
        return

    db.record_chat(
        message.chat.id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if not pixiv_service.get_refresh_token():
        await message.reply("Pixiv: укажи refresh_token в .env файле (PIXIV_REFRESH_TOKEN).")
        return

    if await antispam.is_spam(user_id, message.chat.id):
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    if not raw_args:
        await message.reply("❌ Использование: <code>/pixiv [теги] [кол-во]</code>\nПример: <code>/pixiv 1girl 2</code>\n<i>⚠️ Теги пишите только на английском!</i>", parse_mode="HTML")
        return

    async with TrackChatTask(message.chat.id):
        tags, count = parse_tags_and_count(raw_args, message.chat.id)
        posts = await pixiv_service.search(tags, limit=count * 3, r18_only=False)
        if not posts:
            await message.reply("Ничего не найдено на Pixiv!")
            return

        sent = await send_posts(
            bot=message.bot,
            chat_id=message.chat.id,
            posts=posts,
            requested_tags=tags,
            count=count,
            reply_to_message_id=message.message_id
        )
        if sent == 0:
            await message.reply("❌ Не удалось отправить арт с Pixiv.")

@router.message(Command("pixivnsfw"))
async def cmd_pixivnsfw(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if db.is_blacklisted(user_id) or db.is_blacklisted(message.chat.id):
        return

    db.record_chat(
        message.chat.id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if not pixiv_service.get_refresh_token():
        await message.reply("Pixiv: укажи refresh_token в .env файле (PIXIV_REFRESH_TOKEN).")
        return

    if await antispam.is_spam(user_id, message.chat.id):
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    if not raw_args:
        await message.reply("❌ Использование: <code>/pixivnsfw [теги] [кол-во]</code>\nПример: <code>/pixivnsfw femboy 2</code>\n<i>⚠️ Теги пишите только на английском!</i>", parse_mode="HTML")
        return

    async with TrackChatTask(message.chat.id):
        tags, count = parse_tags_and_count(raw_args, message.chat.id)
        posts = await pixiv_service.search(tags, limit=count * 3, r18_only=True)
        if not posts:
            await message.reply("Ничего не найдено на Pixiv R-18!")
            return

        sent = await send_posts(
            bot=message.bot,
            chat_id=message.chat.id,
            posts=posts,
            requested_tags=tags,
            count=count,
            reply_to_message_id=message.message_id
        )
        if sent == 0:
            await message.reply("❌ Не удалось отправить арт с Pixiv R-18.")

@router.message(Command("pixivmanga"))
async def cmd_pixivmanga(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if db.is_blacklisted(user_id) or db.is_blacklisted(message.chat.id):
        return

    db.record_chat(
        message.chat.id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    if not pixiv_service.get_refresh_token():
        await message.reply("Pixiv: укажи refresh_token в .env файле (PIXIV_REFRESH_TOKEN).")
        return

    if await antispam.is_spam(user_id, message.chat.id):
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split(maxsplit=1)) > 1 else ""
    if not raw_args:
        await message.reply("❌ Использование: <code>/pixivmanga [теги]</code>\nПример: <code>/pixivmanga futanari</code>\n<i>⚠️ Теги пишите только на английском!</i>", parse_mode="HTML")
        return

    async with TrackChatTask(message.chat.id):
        tags = raw_args.strip()
        status_msg = await message.reply("⏳ Загружаем мангу Pixiv R-18...")
        success = await send_pixiv_manga(
            bot=message.bot,
            chat_id=message.chat.id,
            tags=tags,
            reply_to_message_id=message.message_id
        )
        try:
            await status_msg.delete()
        except Exception:
            pass

        if not success:
            await message.reply("Ничего не найдено или не удалось собрать мангу!")
