import re
import random
import logging
from aiogram import Router, types, F
import config
from database import db
from utils.antispam import antispam
from utils.media import send_posts, send_pixiv_manga
from utils.task_tracker import TrackChatTask
from services.rule34 import rule34_service
from services.danbooru import danbooru_service
from services.pixiv import pixiv_service
from handlers.commands import parse_tags_and_count

logger = logging.getLogger(__name__)

router = Router(name="triggers")

def is_futa_femboy_combo(text_lower: str) -> bool:
    if "фута+фембой" in text_lower or "футафембой" in text_lower or "фута + фембой" in text_lower:
        return True
    return "фута" in text_lower and "фембой" in text_lower

async def search_posts_by_source(source: str, tag: str, count: int = 1, video_only: bool = False, chat_id: int = 0):
    if source == "danbooru":
        posts = await danbooru_service.search(tag, limit=config.POSTS_COUNT)
    elif source == "pixiv":
        posts = await pixiv_service.search(tag, limit=count * 3, video_only=video_only, r18_only=True)
    else:
        posts = await rule34_service.search(tag, limit=config.POSTS_COUNT, antiai=config.is_antiai(chat_id))

    if video_only and posts:
        video_posts = [
            p for p in posts 
            if any(p.get("file_url", "").lower().split("?")[0].endswith(ext) for ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"])
        ]
        if video_posts:
            posts = video_posts

    return posts

@router.message(F.text)
async def triggers_watcher(message: types.Message):
    text = (message.text or "").strip()
    if not text:
        return

    # Игнорируем команды со слэшем и точкой
    if text.startswith("/") or text.startswith("."):
        return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    # Проверка блеклиста
    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        return

    # Запоминаем чат
    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    # Проверка включения триггеров для данного чата
    if not config.is_triggers_enabled(chat_id):
        return

    text_lower = text.lower()

    # 1. Триггер "порно" — случайное видео
    if "порно" in text_lower:
        if await antispam.is_spam(user_id, chat_id):
            return
        async with TrackChatTask(chat_id):
            video_tags = ["video", "animated", "webm", "mp4"]
            tag = random.choice(video_tags)
            source = config.get_default_source(chat_id)
            posts = await search_posts_by_source(source, tag, count=1, video_only=True, chat_id=chat_id)
            if posts:
                await send_posts(
                    bot=message.bot,
                    chat_id=chat_id,
                    posts=posts,
                    requested_tags="",
                    count=1,
                    reply_to_message_id=message.message_id
                )
        return

    # 2. Триггер "фута + фембой" / "фута+фембой" (видео)
    if is_futa_femboy_combo(text_lower):
        if await antispam.is_spam(user_id, chat_id):
            return
        async with TrackChatTask(chat_id):
            source = config.get_default_source(chat_id)
            posts = await search_posts_by_source(source, "futa femboy video", count=1, video_only=True, chat_id=chat_id)
            if posts:
                await send_posts(
                    bot=message.bot,
                    chat_id=chat_id,
                    posts=posts,
                    requested_tags="futa femboy video",
                    count=1,
                    reply_to_message_id=message.message_id
                )
        return

    # 3. Триггер "r34 [теги] [кол-во]"
    r34_match = re.match(r"^r34\s+(.+)$", text, re.IGNORECASE)
    if r34_match:
        if await antispam.is_spam(user_id, chat_id):
            return
        async with TrackChatTask(chat_id):
            tags, count = parse_tags_and_count(r34_match.group(1), chat_id)
            if tags:
                posts = await rule34_service.search(tags, limit=config.POSTS_COUNT, antiai=config.is_antiai(chat_id))
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags=tags,
                        count=count,
                        reply_to_message_id=message.message_id
                    )
        return

    # 4. Триггер "pixivnsfw [теги] [кол-во]"
    pixiv_nsfw_match = re.match(r"^pixivnsfw\s+(.+)$", text, re.IGNORECASE)
    if pixiv_nsfw_match:
        if await antispam.is_spam(user_id, chat_id):
            return
        if not pixiv_service.get_refresh_token():
            return
        async with TrackChatTask(chat_id):
            tags, count = parse_tags_and_count(pixiv_nsfw_match.group(1), chat_id)
            if tags:
                posts = await pixiv_service.search(tags, limit=count * 3, r18_only=True)
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags=tags,
                        count=count,
                        reply_to_message_id=message.message_id
                    )
        return

    # 5. Триггер "pixivmanga [теги]"
    pixiv_manga_match = re.match(r"^pixivmanga\s+(.+)$", text, re.IGNORECASE)
    if pixiv_manga_match:
        if await antispam.is_spam(user_id, chat_id):
            return
        if not pixiv_service.get_refresh_token():
            return
        async with TrackChatTask(chat_id):
            tags = pixiv_manga_match.group(1).strip()
            if tags:
                await send_pixiv_manga(
                    bot=message.bot,
                    chat_id=chat_id,
                    tags=tags,
                    reply_to_message_id=message.message_id
                )
        return

    # 6. Триггер "pixiv [теги] [кол-во]"
    pixiv_match = re.match(r"^pixiv\s+(.+)$", text, re.IGNORECASE)
    if pixiv_match:
        if await antispam.is_spam(user_id, chat_id):
            return
        if not pixiv_service.get_refresh_token():
            return
        async with TrackChatTask(chat_id):
            tags, count = parse_tags_and_count(pixiv_match.group(1), chat_id)
            if tags:
                posts = await pixiv_service.search(tags, limit=count * 3, r18_only=False)
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags=tags,
                        count=count,
                        reply_to_message_id=message.message_id
                    )
        return

    # 7. Одиночный триггер "фута"
    if "фута" in text_lower:
        if await antispam.is_spam(user_id, chat_id):
            return
        async with TrackChatTask(chat_id):
            source = config.get_default_source(chat_id)
            posts = await search_posts_by_source(source, "futa", count=1, video_only=False, chat_id=chat_id)
            if posts:
                await send_posts(
                    bot=message.bot,
                    chat_id=chat_id,
                    posts=posts,
                    requested_tags="futa",
                    count=1,
                    reply_to_message_id=message.message_id
                )
        return

    # 8. Одиночный триггер "фембой"
    if "фембой" in text_lower:
        if await antispam.is_spam(user_id, chat_id):
            return
        async with TrackChatTask(chat_id):
            source = config.get_default_source(chat_id)
            posts = await search_posts_by_source(source, "femboy", count=1, video_only=False, chat_id=chat_id)
            if posts:
                await send_posts(
                    bot=message.bot,
                    chat_id=chat_id,
                    posts=posts,
                    requested_tags="femboy",
                    count=1,
                    reply_to_message_id=message.message_id
                )
        return
