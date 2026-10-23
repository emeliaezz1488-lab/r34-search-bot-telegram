import re
import time
import random
import asyncio
import logging
from pathlib import Path
from aiogram import Router, types, F
from aiogram.enums import ChatAction
from aiogram.types import FSInputFile
import config
from database import db
from utils.filters import smart_parse_tags_and_count
from utils.antispam import antispam
from utils.antidaun import antidaun, TrackUserTask
from utils.media import send_posts, send_pixiv_manga, auto_delete_later
from utils.task_tracker import TrackChatTask
from services.rule34 import rule34_service
from services.danbooru import danbooru_service
from services.pixiv import pixiv_service
from services.konachan import konachan_service
from services.pornhub import pornhub_service

logger = logging.getLogger("triggers")

router = Router(name="triggers")

PHOTO_MAYMAY_PATH = Path(__file__).resolve().parent.parent / "photo_2026-09-03_15-03-34.jpg"
PHOTO_AXIOM_PATH = Path(__file__).resolve().parent.parent / "axiom.jpg"

def is_futa_femboy_combo(text_lower: str) -> bool:
    has_futa = "фута" in text_lower or "futa" in text_lower
    has_femboy = "фембой" in text_lower or "femboy" in text_lower
    return has_futa and has_femboy

async def search_posts_by_source(source: str, tag: str, count: int = 1, video_only: bool = False, chat_id: int = 0):
    t_search = time.time()
    logger.info(f"🔎 [Search:{source.upper()}] Тег: '{tag}' | Только видео: {video_only} | Чат: {chat_id}")
    if source == "danbooru":
        posts = await danbooru_service.search(tag, limit=config.POSTS_COUNT)
    elif source == "pixiv":
        posts = await pixiv_service.search(tag, limit=count * 3, video_only=video_only, r18_only=True)
    elif source == "konachan":
        posts = await konachan_service.search(tag, limit=config.POSTS_COUNT, rating_explicit=True)
    else:
        posts = await rule34_service.search(tag, limit=config.POSTS_COUNT, antiai=config.is_antiai(chat_id))

    if video_only and posts:
        mp4_posts = [p for p in posts if p.get("file_url", "").lower().split("?")[0].endswith(".mp4")]
        other_video_posts = [
            p for p in posts 
            if any(p.get("file_url", "").lower().split("?")[0].endswith(ext) for ext in [".webm", ".mov", ".avi", ".mkv"])
        ]
        video_posts = mp4_posts + other_video_posts
        if video_posts:
            posts = video_posts

    dur = time.time() - t_search
    logger.info(f"✅ [Search:{source.upper()}] Найдено {len(posts)} постов за {dur:.2f}с (mp4 в начале: {video_only})")
    return posts

@router.message(F.text)
async def triggers_watcher(message: types.Message):
    text = (message.text or "").strip()
    if not text:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0
    chat_type = str(message.chat.type)
    username = message.from_user.username or message.from_user.full_name or str(user_id)

    # Игнорируем команды со слэшем и точкой (они идут в router команд)
    if text.startswith("/") or text.startswith("."):
        return

    # Проверка блеклиста
    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        return

    # Запоминаем чат
    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        chat_type
    )

    # Проверка включения триггеров для данного чата
    if not config.is_triggers_enabled(chat_id):
        return

    text_lower = text.lower()

    # 0.1. Триггер "связь"
    if "связь" in text_lower:
        logger.info(f"⚡ [TRIGGER:связь] в чате {chat_id} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            return
        sent = None
        try:
            sent = await message.reply("📞Великая связь!")
        except Exception:
            try:
                sent = await message.bot.send_message(chat_id=chat_id, text="📞Великая связь!")
            except Exception as e:
                logger.error(f"[Trigger:связь] Ошибка отправки: {e}")
        if sent and config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
            asyncio.create_task(auto_delete_later(message.bot, chat_id, [sent.message_id], config.get_auto_delete_delay(chat_id)))
        return

    # 0.2. Триггер "maymay"
    if "maymay" in text_lower:
        logger.info(f"⚡ [TRIGGER:maymay] в чате {chat_id} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            return
        if PHOTO_MAYMAY_PATH.exists():
            input_file = FSInputFile(PHOTO_MAYMAY_PATH)
            sent = None
            try:
                sent = await message.reply_photo(photo=input_file)
            except Exception:
                try:
                    sent = await message.bot.send_photo(chat_id=chat_id, photo=input_file)
                except Exception as e:
                    logger.error(f"[Trigger:maymay] Ошибка отправки фото: {e}")
            if sent and config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
                asyncio.create_task(auto_delete_later(message.bot, chat_id, [sent.message_id], config.get_auto_delete_delay(chat_id)))
        else:
            logger.error(f"[Trigger:maymay] Файл фото не найден: {PHOTO_MAYMAY_PATH}")
        return

    # 0.3. Триггер "semor"
    if "semor" in text_lower:
        logger.info(f"⚡ [TRIGGER:semor] в чате {chat_id} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            return
        if PHOTO_AXIOM_PATH.exists():
            input_file = FSInputFile(PHOTO_AXIOM_PATH)
            sent = None
            try:
                sent = await message.reply_photo(photo=input_file)
            except Exception:
                try:
                    sent = await message.bot.send_photo(chat_id=chat_id, photo=input_file)
                except Exception as e:
                    logger.error(f"[Trigger:semor] Ошибка отправки фото axiom.jpg: {e}")
            if sent and config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
                asyncio.create_task(auto_delete_later(message.bot, chat_id, [sent.message_id], config.get_auto_delete_delay(chat_id)))
        else:
            logger.error(f"[Trigger:semor] Файл axiom.jpg не найден: {PHOTO_AXIOM_PATH}")
        return

    # 1. Триггер "порно [кол-во]" — случайное видео
    if "порно" in text_lower:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        _, count, media_filter = smart_parse_tags_and_count(text, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:порно] сработал в чате {chat_id} (запрошено: {count} шт) от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                video_tags = ["video", "animated", "webm", "mp4"]
                tag = random.choice(video_tags)
                source = config.get_default_source(chat_id)
                posts = await search_posts_by_source(source, tag, count=count, video_only=True, chat_id=chat_id)
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags="",
                        count=count,
                        reply_to_message_id=message.message_id,
                        media_filter=media_filter or "video"
                    )
        return

    # 2. Триггер "фута + фембой [кол-во]" (видео)
    if is_futa_femboy_combo(text_lower):
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        _, count, media_filter = smart_parse_tags_and_count(text, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:фута+фембой] сработал в чате {chat_id} (запрошено: {count} шт) от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_VIDEO)
                source = config.get_default_source(chat_id)
                posts = await search_posts_by_source(source, "futa femboy video", count=count, video_only=True, chat_id=chat_id)
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags="futa femboy video",
                        count=count,
                        reply_to_message_id=message.message_id,
                        media_filter=media_filter or "video"
                    )
        return

    # 3. Триггер "r34 [теги] [кол-во]"
    r34_match = re.match(r"^r34\s+(.+)$", text, re.IGNORECASE)
    if r34_match:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        raw_args = r34_match.group(1)
        tags, count, media_filter = smart_parse_tags_and_count(raw_args, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:r34] в {chat_id}: теги='{tags}', кол-во={count} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                if tags:
                    posts = await rule34_service.search(tags, limit=config.POSTS_COUNT, antiai=config.is_antiai(chat_id))
                    if posts:
                        await send_posts(
                            bot=message.bot,
                            chat_id=chat_id,
                            posts=posts,
                            requested_tags=tags,
                            count=count,
                            reply_to_message_id=message.message_id,
                            media_filter=media_filter
                        )
        return

    # 3.1. Триггер "konachan [теги] [кол-во]" / "коначан [теги] [кол-во]"
    kona_match = re.match(r"^(?:konachan|коначан)\s*(.*)$", text, re.IGNORECASE)
    if kona_match:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        raw_args = kona_match.group(1)
        tags, count, media_filter = smart_parse_tags_and_count(raw_args, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:konachan] в {chat_id}: теги='{tags}', кол-во={count} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                posts = await konachan_service.search(tags, limit=config.POSTS_COUNT)
                if posts:
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
                else:
                    await message.reply("Ничего не найдено на Konachan! (Попробуйте другие теги)")
        return

    # 3.2. Триггер "ph [запрос] [кол-во]" / "порнхаб [запрос] [кол-во]"
    ph_match = re.match(r"^(?:ph|pornhub|порнхаб)\s*(.*)$", text, re.IGNORECASE)
    if ph_match:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        raw_args = ph_match.group(1)
        tags, count, media_filter = smart_parse_tags_and_count(raw_args, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:pornhub] в {chat_id}: запрос='{tags}', кол-во={count} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                posts = await pornhub_service.search(tags, limit=max(count * 3, 10))
                if posts:
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
                        await message.reply("❌ Не удалось отправить превью с Pornhub.")
                else:
                    await message.reply("Ничего не найдено на Pornhub! (Попробуйте другой запрос на английском)")
        return

    # 4. Триггер "pixivnsfw [теги] [кол-во]"
    pixiv_nsfw_match = re.match(r"^(?:pixivnsfw|пиксивнсфв)\s*(.*)$", text, re.IGNORECASE)
    if pixiv_nsfw_match:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        raw_args = pixiv_nsfw_match.group(1)
        tags, count, media_filter = smart_parse_tags_and_count(raw_args, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:pixivnsfw] в {chat_id}: теги='{tags}', кол-во={count} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            return
        if not pixiv_service.get_refresh_token():
            logger.warning("[PixivNSFW] Нет refresh_token")
            await message.reply("⚠️ Pixiv: укажи <code>PIXIV_REFRESH_TOKEN</code> в настройках или .env!", parse_mode="HTML")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                posts = await pixiv_service.search(tags, limit=count * 3, r18_only=True)
                if posts:
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
                        await message.reply("❌ Не удалось отправить арт с Pixiv R-18 (ошибка скачивания медиа).")
                else:
                    err_text = f" (ошибка: <code>{pixiv_service.last_error}</code>)" if pixiv_service.last_error else ""
                    await message.reply(f"Ничего не найдено на Pixiv R-18!{err_text}", parse_mode="HTML")
        return

    # 5. Триггер "pixivmanga [теги]"
    pixiv_manga_match = re.match(r"^(?:pixivmanga|пиксивманга)\s*(.*)$", text, re.IGNORECASE)
    if pixiv_manga_match:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        logger.info(f"⚡ [TRIGGER:pixivmanga] сработал в чате {chat_id} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            return
        if not pixiv_service.get_refresh_token():
            await message.reply("⚠️ Pixiv: укажи <code>PIXIV_REFRESH_TOKEN</code> в настройках или .env!", parse_mode="HTML")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                tags = pixiv_manga_match.group(1).strip()
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
                    err_text = f" (ошибка: <code>{pixiv_service.last_error}</code>)" if pixiv_service.last_error else ""
                    await message.reply(f"Ничего не найдено или не удалось собрать мангу!{err_text}", parse_mode="HTML")
        return

    # 6. Триггер "pixiv [теги] [кол-во]"
    pixiv_match = re.match(r"^(?:pixiv|пиксив)\s*(.*)$", text, re.IGNORECASE)
    if pixiv_match and not text.lower().startswith(("pixivnsfw", "пиксивнсфв", "pixivmanga", "пиксивманга")):
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        raw_args = pixiv_match.group(1)
        tags, count, media_filter = smart_parse_tags_and_count(raw_args, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:pixiv] в {chat_id}: теги='{tags}', кол-во={count} от {username}")
        if await antispam.is_spam(user_id, chat_id):
            return
        if not pixiv_service.get_refresh_token():
            await message.reply("⚠️ Pixiv: укажи <code>PIXIV_REFRESH_TOKEN</code> в настройках или .env!", parse_mode="HTML")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                posts = await pixiv_service.search(tags, limit=count * 3, r18_only=False)
                if posts:
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
                        await message.reply("❌ Не удалось отправить арт с Pixiv (ошибка скачивания медиа).")
                else:
                    err_text = f" (ошибка: <code>{pixiv_service.last_error}</code>)" if pixiv_service.last_error else ""
                    await message.reply(f"Ничего не найдено на Pixiv!{err_text}", parse_mode="HTML")
        return

    # 7. Одиночный триггер "фута [кол-во]"
    if "фута" in text_lower:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        _, count, media_filter = smart_parse_tags_and_count(text, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:фута] сработал в чате {chat_id} (запрошено: {count} шт) от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                source = config.get_default_source(chat_id)
                posts = await search_posts_by_source(source, "futa", count=count, video_only=False, chat_id=chat_id)
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags="futa",
                        count=count,
                        reply_to_message_id=message.message_id,
                        media_filter=media_filter
                    )
        return

    # 8. Одиночный триггер "фембой [кол-во]"
    if "фембой" in text_lower:
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        _, count, media_filter = smart_parse_tags_and_count(text, chat_id, user_id)
        logger.info(f"⚡ [TRIGGER:фембой] сработал в чате {chat_id} (запрошено: {count} шт) от {username}")
        if await antispam.is_spam(user_id, chat_id):
            logger.warning(f"🚫 Анти-спам сработал на {username} ({user_id})")
            return
        if not await antidaun.can_start(user_id):
            await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
            return
        antidaun.record_request(user_id)
        async with TrackUserTask(user_id):
            async with TrackChatTask(chat_id):
                await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                source = config.get_default_source(chat_id)
                posts = await search_posts_by_source(source, "femboy", count=count, video_only=False, chat_id=chat_id)
                if posts:
                    await send_posts(
                        bot=message.bot,
                        chat_id=chat_id,
                        posts=posts,
                        requested_tags="femboy",
                        count=count,
                        reply_to_message_id=message.message_id,
                        media_filter=media_filter
                    )
        return

    # 9. Если сообщение отправлено в ЛИЧКУ боту (private chat) — прямой поиск без префикса
    if chat_type == "private":
        can_proceed, wait_time = antidaun.check_rate_limit(user_id)
        if not can_proceed:
            await message.reply(f"⏳ <b>[Rate-Limit]</b> Запросы доступны раз в 15 секунд! Подождите ещё <code>{wait_time}с</code>.", parse_mode="HTML")
            return
        tags, count, media_filter = smart_parse_tags_and_count(text, chat_id, user_id)
        if tags:
            logger.info(f"⚡ [DIRECT PRIVATE SEARCH] Теги: '{tags}', кол-во: {count} от {username}")
            if await antispam.is_spam(user_id, chat_id):
                return
            if not await antidaun.can_start(user_id):
                await message.reply("⚠️ <b>[Anti-Spam]</b> У вас уже есть 2 активных запроса. Дождитесь их завершения!", parse_mode="HTML")
                return
            antidaun.record_request(user_id)
            async with TrackUserTask(user_id):
                async with TrackChatTask(chat_id):
                    await message.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO)
                    source = config.get_default_source(chat_id)
                    posts = await search_posts_by_source(source, tags, count=count, video_only=False, chat_id=chat_id)
                    if posts:
                        await send_posts(
                            bot=message.bot,
                            chat_id=chat_id,
                            posts=posts,
                            requested_tags=tags,
                            count=count,
                            reply_to_message_id=message.message_id,
                            media_filter=media_filter
                        )
                    else:
                        await message.reply("Ничего не найдено!")
