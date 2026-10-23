from pathlib import Path
import os
import io
import time
import shutil
import asyncio
import logging
import html
import tempfile
import subprocess
from typing import List, Dict, Optional, Tuple, Union
from PIL import Image
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo, Message
import config
from utils.recent import recent_tracker
from utils.http_client import fast_download
from services.pixiv import pixiv_service

logger = logging.getLogger("media")

def normalize_image_for_telegram(raw_bytes: bytes, original_ext: str) -> Tuple[bytes, str]:
    """
    Нормализует изображение для гарантированной отправки через Telegram Bot API (включая альбомы send_media_group):
    1. Конвертирует WEBP, TIFF, BMP, PNG и любые другие форматы в чистый JPEG.
    2. Проверяет и исправляет соотношение сторон (Telegram запрещает > 20:1 / PHOTO_INVALID_DIMENSIONS).
    3. Масштабирует гигантские обои/сканы до 2048px (максимум для Telegram viewer),
       что снижает вес альбома из 10 картинок с 40 МБ до 3-4 МБ, предотвращая тайм-ауты и ошибку 413.
    """
    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            w, h = img.size
            if w <= 0 or h <= 0:
                return raw_bytes, "jpg"

            ratio = max(w / h, h / w)

            # Конвертируем в RGB
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                mask = None
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if 'A' in img.getbands():
                    mask = img.split()[-1]
                rgb_img.paste(img, mask=mask)
                work_img = rgb_img
            elif img.mode != 'RGB':
                work_img = img.convert('RGB')
            else:
                work_img = img.copy()

            # Если соотношение сторон слишком экстремальное (> 19.5:1), добавляем поля
            if ratio > 19.5:
                if w > h:
                    new_h = int(w / 10)
                    padded = Image.new('RGB', (w, new_h), (255, 255, 255))
                    padded.paste(work_img, (0, (new_h - h) // 2))
                    work_img = padded
                else:
                    new_w = int(h / 10)
                    padded = Image.new('RGB', (new_w, h), (255, 255, 255))
                    padded.paste(work_img, ((new_w - w) // 2, 0))
                    work_img = padded

            # Масштабируем до 2048px (Telegram всё равно сжимает фото крупнее 2048px)
            max_side = max(work_img.size)
            if max_side > 2048:
                scale = 2048 / max_side
                new_size = (int(work_img.width * scale), int(work_img.height * scale))
                work_img = work_img.resize(new_size, Image.Resampling.LANCZOS)

            out_buf = io.BytesIO()
            work_img.save(out_buf, format='JPEG', quality=85, optimize=True)
            res_bytes = out_buf.getvalue()

            if len(res_bytes) > 8 * 1024 * 1024:
                out_buf = io.BytesIO()
                work_img.save(out_buf, format='JPEG', quality=70, optimize=True)
                res_bytes = out_buf.getvalue()

            return res_bytes, "jpg"
    except Exception as e:
        logger.warning(f"⚠️ [ImageNorm] Ошибка нормализации картинки ({e}), используем исходные байты")
        return raw_bytes, original_ext

async def download_file(url: str, referer: Optional[str] = None) -> Optional[bytes]:
    return await fast_download(url, referer)

_CACHED_FFMPEG_BIN: Optional[str] = None

def get_ffmpeg_binary() -> Optional[str]:
    """
    Автоматическое обнаружение ffmpeg:
    1. Системный ffmpeg (PATH)
    2. Автономный статический бинарник imageio-ffmpeg (для Pterodactyl / Docker без root)
    3. Локальный бинарник в папке бота (./ffmpeg или ./ffmpeg.exe)
    """
    global _CACHED_FFMPEG_BIN
    if _CACHED_FFMPEG_BIN and os.path.exists(_CACHED_FFMPEG_BIN):
        return _CACHED_FFMPEG_BIN

    # 1. Системный PATH
    sys_bin = shutil.which("ffmpeg")
    if sys_bin:
        _CACHED_FFMPEG_BIN = sys_bin
        return sys_bin

    # 2. imageio-ffmpeg (автономный бинарник для Pterodactyl контейнеров без root)
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            _CACHED_FFMPEG_BIN = exe
            logger.info(f"🎬 [FFmpeg] Найден автономный бинарник imageio-ffmpeg: {exe}")
            return exe
    except Exception:
        pass

    # 3. Локальный бинарник в корне бота
    base_dir = Path(__file__).resolve().parent.parent
    for name in ["ffmpeg", "ffmpeg.exe"]:
        cand = base_dir / name
        if cand.exists():
            _CACHED_FFMPEG_BIN = str(cand.resolve())
            logger.info(f"🎬 [FFmpeg] Найден локальный бинарник: {_CACHED_FFMPEG_BIN}")
            return _CACHED_FFMPEG_BIN

    return None

def make_streamable_mp4_sync(media_bytes: bytes, ext: str) -> Optional[bytes]:
    ext = (ext or "").lower()
    # Если это уже MP4 — мгновенно отдаем без нагрузки на процессор VDS!
    if ext == "mp4":
        return media_bytes

    ffmpeg_bin = get_ffmpeg_binary()
    if not ffmpeg_bin:
        logger.warning("⚠️ [FFmpeg] Бинарник ffmpeg не найден (Pterodactyl). Установите imageio-ffmpeg.")
        return None

    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as f_in:
            f_in.write(media_bytes)
            tmp_in = f_in.name

        tmp_out = tmp_in + "_conv.mp4"
        # Для webm/gif используем быстрый пресет ultrafast
        cmd = [
            ffmpeg_bin, "-y", "-i", tmp_in,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-preset", "ultrafast",
            "-threads", "0",
            "-c:a", "aac", "-b:a", "128k",
            tmp_out
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30)
        if res.returncode == 0 and os.path.exists(tmp_out):
            with open(tmp_out, "rb") as f:
                return f.read()
    except Exception as e:
        logger.error(f"[Media] ffmpeg conversion error: {e}")
    finally:
        for p in (tmp_in, tmp_out):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
    return None

async def _safe_send_photo(
    bot: Bot,
    chat_id: int,
    photo: BufferedInputFile,
    caption: str,
    spoiler: bool,
    reply_to_id: Optional[int],
    post_id: str = ""
) -> Optional[Message]:
    t0 = time.time()
    size_kb = len(photo.data) / 1024
    size_str = f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
    logger.info(f"📤 [Telegram] Отправка фото #{post_id} ({size_str}) в чат {chat_id}...")
    try:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
            has_spoiler=spoiler,
            reply_to_message_id=reply_to_id
        )
        logger.info(f"🚀 [Telegram] Фото #{post_id} доставлено за {time.time() - t0:.2f}с (msg_id: {msg.message_id})")
        return msg
    except Exception as e:
        err_str = str(e)
        if "PHOTO_INVALID_DIMENSIONS" in err_str or "dimensions" in err_str.lower():
            logger.info(f"📄 [Telegram] Фото #{post_id} имеет нестандартные пропорции (>20:1), отправляем документом...")
            try:
                msg = await bot.send_document(
                    chat_id=chat_id,
                    document=photo,
                    caption=caption,
                    parse_mode="HTML",
                    reply_to_message_id=reply_to_id
                )
                logger.info(f"🚀 [Telegram] Документ #{post_id} доставлен за {time.time() - t0:.2f}с (msg_id: {msg.message_id})")
                return msg
            except Exception as e_doc:
                logger.error(f"❌ [Telegram] Ошибка отправки документа #{post_id}: {e_doc}")
                return None

        if reply_to_id:
            logger.debug(f"[Media] send_photo with reply_to failed ({e}), trying without reply...")
            try:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=caption,
                    parse_mode="HTML",
                    has_spoiler=spoiler
                )
                logger.info(f"🚀 [Telegram] Фото #{post_id} доставлено за {time.time() - t0:.2f}с (msg_id: {msg.message_id})")
                return msg
            except Exception as e2:
                err_str2 = str(e2)
                if "PHOTO_INVALID_DIMENSIONS" in err_str2 or "dimensions" in err_str2.lower():
                    logger.info(f"📄 [Telegram] Фото #{post_id} имеет нестандартные пропорции (>20:1), отправляем документом...")
                    try:
                        msg = await bot.send_document(
                            chat_id=chat_id,
                            document=photo,
                            caption=caption,
                            parse_mode="HTML"
                        )
                        logger.info(f"🚀 [Telegram] Документ #{post_id} доставлен за {time.time() - t0:.2f}с (msg_id: {msg.message_id})")
                        return msg
                    except Exception as e_doc2:
                        logger.error(f"❌ [Telegram] Ошибка отправки документа #{post_id}: {e_doc2}")
                        return None
                logger.error(f"❌ [Telegram] Ошибка отправки фото #{post_id}: {e2}")
        else:
            logger.error(f"❌ [Telegram] Ошибка отправки фото #{post_id}: {e}")
    return None

async def _safe_send_video(
    bot: Bot,
    chat_id: int,
    video: BufferedInputFile,
    caption: str,
    spoiler: bool,
    reply_to_id: Optional[int],
    post_id: str = ""
) -> Optional[Message]:
    t0 = time.time()
    size_kb = len(video.data) / 1024
    size_str = f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
    logger.info(f"📤 [Telegram] Отправка видео #{post_id} ({size_str}) в чат {chat_id}...")
    try:
        msg = await bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=caption,
            parse_mode="HTML",
            has_spoiler=spoiler,
            supports_streaming=True,
            reply_to_message_id=reply_to_id
        )
        logger.info(f"🚀 [Telegram] Видео #{post_id} доставлено за {time.time() - t0:.2f}с (msg_id: {msg.message_id})")
        return msg
    except Exception as e:
        logger.debug(f"[Media] send_video failed ({e}), пробуем отправить документом...")
        try:
            msg = await bot.send_document(
                chat_id=chat_id,
                document=video,
                caption=caption,
                parse_mode="HTML",
                reply_to_message_id=reply_to_id
            )
            logger.info(f"🚀 [Telegram] Видео #{post_id} доставлено документом за {time.time() - t0:.2f}с (msg_id: {msg.message_id})")
            return msg
        except Exception as e2:
            logger.error(f"❌ [Telegram] Ошибка отправки видео/документа #{post_id}: {e2}")
    return None

async def _safe_send_media_group(
    bot: Bot,
    chat_id: int,
    media: List[Union[InputMediaPhoto, InputMediaVideo]],
    reply_to_id: Optional[int] = None
) -> List[Message]:
    t0 = time.time()
    logger.info(f"📤 [Telegram] Отправка альбома из {len(media)} медиа в чат {chat_id}...")
    try:
        msgs = await bot.send_media_group(
            chat_id=chat_id,
            media=media,
            reply_to_message_id=reply_to_id
        )
        logger.info(f"🚀 [Telegram] Альбом из {len(media)} медиа доставлен за {time.time() - t0:.2f}с")
        return list(msgs)
    except Exception as e:
        logger.warning(f"⚠️ [Telegram] Ошибка send_media_group ({e}), пробуем восстановить отправку...")

        # 1. Если в альбоме 4 и более медиа, делим пополам на 2 меньших альбома
        if len(media) >= 4:
            mid = len(media) // 2
            try:
                part1 = media[:mid]
                part2 = media[mid:]
                res = []
                m1 = await bot.send_media_group(chat_id=chat_id, media=part1, reply_to_message_id=reply_to_id)
                res.extend(list(m1))
                await asyncio.sleep(0.3)
                m2 = await bot.send_media_group(chat_id=chat_id, media=part2)
                res.extend(list(m2))
                logger.info(f"🚀 [Telegram] Альбом успешно доставлен 2 частями ({len(part1)} + {len(part2)})!")
                return res
            except Exception as e_split:
                logger.debug(f"[Telegram] Попытка разделения на 2 пачки не удалась: {e_split}")

        # 2. Если в альбоме 3 медиа, пробуем отправить 2 альбомом и 1 одиночным
        if len(media) == 3:
            try:
                res = []
                m1 = await bot.send_media_group(chat_id=chat_id, media=media[:2], reply_to_message_id=reply_to_id)
                res.extend(list(m1))
                await asyncio.sleep(0.3)
                last_item = media[2]
                if isinstance(last_item, InputMediaVideo):
                    m2 = await _safe_send_video(bot, chat_id, last_item.media, last_item.caption or "", last_item.has_spoiler or False, None)
                else:
                    m2 = await _safe_send_photo(bot, chat_id, last_item.media, last_item.caption or "", last_item.has_spoiler or False, None)
                if m2:
                    res.append(m2)
                logger.info(f"🚀 [Telegram] Альбом из 3 медиа доставлен как 2+1!")
                return res
            except Exception as e_split3:
                logger.debug(f"[Telegram] Попытка 2+1 не удалась: {e_split3}")

        # 3. Если ошибка была из-за смешанных типов (видео+фото), отправляем фото альбомом
        photos = [m for m in media if isinstance(m, InputMediaPhoto)]
        if len(photos) >= 2 and len(photos) != len(media):
            try:
                msgs = list(await bot.send_media_group(
                    chat_id=chat_id,
                    media=photos,
                    reply_to_message_id=reply_to_id
                ))
                logger.info(f"🚀 [Telegram] Альбом из {len(photos)} фото успешно доставлен!")
                videos = [m for m in media if isinstance(m, InputMediaVideo)]
                for v in videos:
                    try:
                        vm = await _safe_send_video(
                            bot=bot,
                            chat_id=chat_id,
                            video=v.media,
                            caption=v.caption or "",
                            spoiler=v.has_spoiler or False
                        )
                        if vm:
                            msgs.append(vm)
                    except Exception:
                        pass
                return msgs
            except Exception as e_photo:
                logger.debug(f"[Telegram] Повторная отправка альбома фото не удалась: {e_photo}")

        # 4. Крайний случай — отправляем по отдельности
        sent_messages = []
        for i, item in enumerate(media):
            cur_reply = reply_to_id if i == 0 else None
            try:
                if isinstance(item, InputMediaVideo):
                    m = await _safe_send_video(
                        bot=bot,
                        chat_id=chat_id,
                        video=item.media,
                        caption=item.caption or "",
                        spoiler=item.has_spoiler or False,
                        reply_to_id=cur_reply
                    )
                else:
                    m = await _safe_send_photo(
                        bot=bot,
                        chat_id=chat_id,
                        photo=item.media,
                        caption=item.caption or "",
                        spoiler=item.has_spoiler or False,
                        reply_to_id=cur_reply
                    )
                if m:
                    sent_messages.append(m)
            except Exception as e_ind:
                logger.error(f"❌ [Telegram] Ошибка одиночной отправки из альбома: {e_ind}")
        return sent_messages

async def auto_delete_later(bot: Bot, chat_id: int, message_ids: List[int], delay: int):
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    for mid in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass

_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(5)

async def _fetch_media_item(post: Dict) -> Optional[Tuple[Dict, BufferedInputFile, bool, str]]:
    async with _DOWNLOAD_SEMAPHORE:
        t0 = time.time()
        file_url = post.get("file_url")
        post_id = str(post.get("id", ""))
        source = post.get("source", "")
        if not file_url:
            return None

        file_ext = file_url.lower().split('?')[0].split('.')[-1]
        is_video = file_ext in ['mp4', 'webm', 'gif', 'mov', 'avi', 'mkv']
        logger.info(f"📥 [Download] Старт #{post_id} ({'видео' if is_video else 'фото'}, {source or 'booru'}, {file_ext})...")

        try:
            if source == "pixiv" or "pximg.net" in file_url:
                raw_bytes = await pixiv_service.download_image(file_url)
                if not raw_bytes:
                    logger.warning(f"⚠️ [Download] #{post_id} Pixiv вернул пустые байты")
                    return None
                norm_bytes, norm_ext = normalize_image_for_telegram(raw_bytes, "jpg")
                dur = time.time() - t0
                size_kb = len(norm_bytes) / 1024
                logger.info(f"✅ [Download] #{post_id} Pixiv скачан и нормализован: {size_kb:.1f} KB за {dur:.2f}с")
                return (post, BufferedInputFile(norm_bytes, filename=f"{post_id or 'pixiv'}.{norm_ext}"), False, post_id)
            elif is_video:
                raw_bytes = await download_file(file_url)
                if not raw_bytes:
                    logger.warning(f"⚠️ [Download] #{post_id} видео вернуло пустые байты")
                    return None
                dur_dl = time.time() - t0
                size_kb = len(raw_bytes) / 1024
                size_str = f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
                logger.info(f"✅ [Download] #{post_id} видео ({file_ext}) скачано: {size_str} за {dur_dl:.2f}с")

                if len(raw_bytes) > 48 * 1024 * 1024:
                    logger.warning(f"⚠️ [Download] #{post_id} видео превышает лимит Telegram ({len(raw_bytes)/(1024*1024):.1f} MB > 48 MB), пропускаем")
                    return None

                if file_ext == "mp4":
                    video_data = raw_bytes
                    out_ext = "mp4"
                else:
                    t_conv = time.time()
                    logger.info(f"⚙️ [FFmpeg] Конвертация #{post_id} ({file_ext} -> MP4)...")
                    processed_bytes = await asyncio.to_thread(make_streamable_mp4_sync, raw_bytes, file_ext)
                    if processed_bytes:
                        dur_conv = time.time() - t_conv
                        video_data = processed_bytes
                        out_ext = "mp4"
                        logger.info(f"⚙️ [FFmpeg] Конвертация #{post_id} завершена за {dur_conv:.2f}с")
                    else:
                        logger.warning(f"⚠️ [FFmpeg] Конвертация #{post_id} ({file_ext}) не удалась, пропускаем")
                        return None

                return (post, BufferedInputFile(video_data, filename=f"{post_id or 'video'}.{out_ext}"), True, post_id)
            else:
                raw_bytes = await download_file(file_url)
                if not raw_bytes:
                    logger.warning(f"⚠️ [Download] #{post_id} фото вернуло пустые байты")
                    return None
                norm_bytes, norm_ext = normalize_image_for_telegram(raw_bytes, file_ext)
                dur = time.time() - t0
                size_kb = len(norm_bytes) / 1024
                size_str = f"{size_kb / 1024:.2f} MB" if size_kb > 1024 else f"{size_kb:.1f} KB"
                logger.info(f"✅ [Download] #{post_id} фото скачано и нормализовано: {size_str} за {dur:.2f}с")
                return (post, BufferedInputFile(norm_bytes, filename=f"{post_id or 'image'}.{norm_ext}"), False, post_id)
        except Exception as e:
            logger.error(f"❌ [Download] Ошибка подготовки медиа #{post_id}: {e}")
            return None

def build_media_chunks(
    items: List[Tuple[Dict, BufferedInputFile, bool, str]],
    max_items_per_chunk: int = 10,
    max_bytes_per_chunk: int = 40 * 1024 * 1024
) -> List[List[Tuple[Dict, BufferedInputFile, bool, str]]]:
    """
    Умное разделение медиа на пачки (альбомы) с учетом жестких лимитов Telegram:
    1. Не более 10 медиа в одном альбоме (ограничение Telegram sendMediaGroup).
    2. Суммарный вес всех медиа в одном multipart-запросе не более 40 МБ (лимит Telegram Bot API 50 МБ).
    Благодаря этому видео всегда объединяются в альбомы вместо падения по таймауту/лимиту!
    """
    chunks = []
    current_chunk = []
    current_bytes = 0

    for item in items:
        _, input_file, is_video, _ = item
        item_size = len(input_file.data)

        # Если добавление файла превысит 10 штук ИЛИ суммарный размер превысит 40 МБ
        if current_chunk and (len(current_chunk) >= max_items_per_chunk or (current_bytes + item_size > max_bytes_per_chunk)):
            chunks.append(current_chunk)
            current_chunk = []
            current_bytes = 0

        current_chunk.append(item)
        current_bytes += item_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

async def send_posts(
    bot: Bot,
    chat_id: int,
    posts: List[Dict],
    requested_tags: str,
    count: int = 1,
    reply_to_message_id: Optional[int] = None,
    media_filter: Optional[str] = None
) -> int:
    if not posts:
        return 0

    target_filter = media_filter or config.get_media_filter(chat_id)
    if target_filter == "photo":
        filtered = [
            p for p in posts 
            if not any(p.get("file_url", "").lower().split("?")[0].endswith(ext) for ext in [".mp4", ".webm", ".gif", ".mov", ".avi", ".mkv"])
        ]
        if filtered:
            posts = filtered
    elif target_filter == "video":
        filtered = [
            p for p in posts 
            if any(p.get("file_url", "").lower().split("?")[0].endswith(ext) for ext in [".mp4", ".webm", ".mov", ".avi", ".mkv"])
        ]
        if filtered:
            posts = filtered
    elif target_filter == "gif":
        filtered = [
            p for p in posts 
            if any(p.get("file_url", "").lower().split("?")[0].endswith(ext) for ext in [".gif", ".webm"])
        ]
        if filtered:
            posts = filtered

    total_start = time.time()
    count = max(1, count)

    import random
    # Keep the caller's results reusable for retries and other handlers.
    posts = list(posts)
    random.shuffle(posts)

    tag_key = requested_tags.strip() if requested_tags.strip() else "random"
    sent_count = 0
    sent_msg_ids = []
    caption = "🔞 <b>Найден пост!</b>"
    spoiler = config.is_spoiler_media(chat_id)

    # Приоритет постам, которые ещё не показывались недавно
    unseen_posts = [p for p in posts if p.get("file_url") and not recent_tracker.is_recent(tag_key, str(p.get("id", "")))]
    posts_to_send = unseen_posts if unseen_posts else [p for p in posts if p.get("file_url")]

    # Загружаем ровно столько медиа, сколько запрошено
    batch_candidates = posts_to_send[:count]
    batch_start = time.time()
    logger.info(f"📦 [Batch] Старт загрузки {len(batch_candidates)} постов...")
    prepared_results = await asyncio.gather(*[_fetch_media_item(p) for p in batch_candidates])
    logger.info(f"📦 [Batch] Загрузка завершена за {time.time() - batch_start:.2f}с (успешно: {sum(1 for x in prepared_results if x is not None)}/{len(batch_candidates)})")

    valid_items = [x for x in prepared_results if x is not None]

    # Если в батче кто-то не скачался, добираем из оставшихся постов
    if len(valid_items) < count and len(posts_to_send) > len(batch_candidates):
        for post in posts_to_send[len(batch_candidates):]:
            if len(valid_items) >= count:
                break
            item = await _fetch_media_item(post)
            if item:
                valid_items.append(item)

    if not valid_items:
        return 0

    final_items = valid_items[:count]

    # Если это Pornhub — формируем информативную подпись
    p0 = final_items[0][0]
    if p0.get("source") == "pornhub":
        title = html.escape(str(p0.get("title", "Pornhub Video")))
        dur = p0.get("duration", "")
        raw_views = p0.get("views", "")
        if isinstance(raw_views, (int, float)):
            views_str = f"{int(raw_views):,}"
        else:
            views_str = str(raw_views).strip()
        rating = p0.get("rating", "")
        rating_str = f" | ⭐ <code>{rating}%</code>" if rating else ""
        web_url = p0.get("web_url", "")
        dur_str = f"⏱ <b>Длительность:</b> <code>{dur}</code> | " if dur else ""
        views_part = f"👁 <b>Просмотры:</b> <code>{views_str}</code>" if views_str else ""
        caption = (
            f"🔞 <b>{title}</b>\n"
            f"{dur_str}{views_part}{rating_str}\n"
            f"🔗 <a href='{web_url}'>Смотреть на Pornhub</a>"
        )
    else:
        caption = "🔞 <b>Найден пост!</b>"

    # Если запрошен/найден 1 элемент — отправляем одиночным сообщением
    if len(final_items) == 1:
        post, input_file, is_video, post_id = final_items[0]
        if is_video:
            msg = await _safe_send_video(
                bot=bot,
                chat_id=chat_id,
                video=input_file,
                caption=caption,
                spoiler=spoiler,
                reply_to_id=reply_to_message_id,
                post_id=post_id
            )
        else:
            msg = await _safe_send_photo(
                bot=bot,
                chat_id=chat_id,
                photo=input_file,
                caption=caption,
                spoiler=spoiler,
                reply_to_id=reply_to_message_id,
                post_id=post_id
            )
        if msg:
            sent_count = 1
            sent_msg_ids.append(msg.message_id)
            recent_tracker.add(tag_key, post_id)
            source_tag_key = post.get("_recent_key")
            if source_tag_key and source_tag_key != tag_key:
                recent_tracker.add(source_tag_key, post_id)
    else:
        # Если 2 и более элементов — группируем в АЛЬБОМЫ с учетом размера (до 10 шт и до 40 МБ на альбом)
        # Пользователь получает 1 сообщение-альбом вместо спама 5-10 сообщениями!
        for chunk_idx, chunk in enumerate(build_media_chunks(final_items, max_items_per_chunk=10, max_bytes_per_chunk=40 * 1024 * 1024)):
            cur_reply = reply_to_message_id if chunk_idx == 0 else None
            if len(chunk) == 1:
                post, input_file, is_video, post_id = chunk[0]
                if is_video:
                    msg = await _safe_send_video(
                        bot=bot,
                        chat_id=chat_id,
                        video=input_file,
                        caption=caption,
                        spoiler=spoiler,
                        reply_to_id=cur_reply,
                        post_id=post_id
                    )
                else:
                    msg = await _safe_send_photo(
                        bot=bot,
                        chat_id=chat_id,
                        photo=input_file,
                        caption=caption,
                        spoiler=spoiler,
                        reply_to_id=cur_reply,
                        post_id=post_id
                    )
                if msg:
                    sent_count += 1
                    sent_msg_ids.append(msg.message_id)
                    recent_tracker.add(tag_key, post_id)
                    source_tag_key = post.get("_recent_key")
                    if source_tag_key and source_tag_key != tag_key:
                        recent_tracker.add(source_tag_key, post_id)
            else:
                media_group = []
                for j, (post, input_file, is_video, post_id) in enumerate(chunk):
                    # Подпись ставим только на первый элемент альбома
                    item_caption = caption if j == 0 else None
                    if is_video:
                        media_group.append(
                            InputMediaVideo(
                                media=input_file,
                                caption=item_caption,
                                parse_mode="HTML",
                                has_spoiler=spoiler,
                                supports_streaming=True
                            )
                        )
                    else:
                        media_group.append(
                            InputMediaPhoto(
                                media=input_file,
                                caption=item_caption,
                                parse_mode="HTML",
                                has_spoiler=spoiler
                            )
                        )

                delivered = await _safe_send_media_group(
                    bot=bot,
                    chat_id=chat_id,
                    media=media_group,
                    reply_to_id=cur_reply
                )
                for m in delivered:
                    sent_msg_ids.append(m.message_id)
                sent_count += len(delivered)
                for _, _, _, post_id in chunk:
                    recent_tracker.add(tag_key, post_id)
                for post, _, _, post_id in chunk:
                    source_tag_key = post.get("_recent_key")
                    if source_tag_key and source_tag_key != tag_key:
                        recent_tracker.add(source_tag_key, post_id)

    total_time = time.time() - total_start
    logger.info(f"✨ [Finish] Успешно отправлено {sent_count}/{count} в чат {chat_id} | Общее время: {total_time:.2f}с")

    if sent_count > 0 and config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
        asyncio.create_task(auto_delete_later(bot, chat_id, sent_msg_ids, config.get_auto_delete_delay(chat_id)))

    return sent_count

async def send_pixiv_manga(
    bot: Bot,
    chat_id: int,
    tags: str,
    reply_to_message_id: Optional[int] = None
) -> bool:
    max_pages = config.get_pixiv_manga_max_pages(chat_id)
    album_info = await pixiv_service.create_manga_album(tags, max_pages=max_pages)
    if not album_info or not album_info.get("pages"):
        return False

    pages_bytes = album_info["pages"]
    title = album_info.get("title", tags or "Pixiv Manga")
    post_id = album_info.get("id", "")
    spoiler = config.is_spoiler_media(chat_id)
    total_pages = len(pages_bytes)

    logger.info(f"[Manga] Найдена манга '{title}' ({total_pages} стр.), отправляем отдельными сообщениями...")

    sent_msg_ids = []
    for idx, page_bytes in enumerate(pages_bytes, start=1):
        input_file = BufferedInputFile(page_bytes, filename=f"page_{idx}.jpg")
        cap = f"📖 <b>{title}</b> ({idx}/{total_pages})"
        cur_reply = reply_to_message_id if idx == 1 else None

        sent_msg = await _safe_send_photo(
            bot=bot,
            chat_id=chat_id,
            photo=input_file,
            caption=cap,
            spoiler=spoiler,
            reply_to_id=cur_reply
        )
        if sent_msg:
            sent_msg_ids.append(sent_msg.message_id)
            logger.info(f"[Manga] 📄 Отправлена страница {idx}/{total_pages} в {chat_id}")

        await asyncio.sleep(0.35)

    if sent_msg_ids:
        if config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
            asyncio.create_task(auto_delete_later(bot, chat_id, sent_msg_ids, config.get_auto_delete_delay(chat_id)))
        return True

    return False
