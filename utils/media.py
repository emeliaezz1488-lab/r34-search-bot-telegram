import os
import io
import shutil
import asyncio
import logging
import tempfile
import subprocess
from typing import List, Dict, Optional, Tuple
import aiohttp
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message
import config
from utils.recent import recent_tracker
from services.pixiv import pixiv_service

logger = logging.getLogger(__name__)

async def download_file(url: str, referer: Optional[str] = None) -> Optional[bytes]:
    headers = config.get_request_headers()
    if referer:
        headers["Referer"] = referer
    elif "pixiv.net" in url or "pximg.net" in url:
        headers["Referer"] = config.PIXIV_REFERER

    try:
        timeout = aiohttp.ClientTimeout(total=45)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.error(f"[Media] Download failed with status {resp.status} for {url}")
    except Exception as e:
        logger.error(f"[Media] Error downloading {url}: {e}")
    return None

def video_has_audio_sync(url: str) -> bool:
    if not shutil.which("ffprobe"):
        return True
    try:
        ua = config.get_random_user_agent()
        probe = subprocess.run(
            [
                "ffprobe", "-user_agent", ua,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                url,
            ],
            capture_output=True, timeout=15,
        )
        if probe.returncode != 0:
            return True
        return bool(probe.stdout.strip())
    except Exception as e:
        logger.error(f"[Media] ffprobe error: {e}")
        return True

def make_streamable_mp4_sync(media_bytes: bytes, ext: str) -> Optional[bytes]:
    ext = (ext or "").lower()
    if not shutil.which("ffmpeg"):
        return media_bytes if ext == "mp4" else None

    tmp_in = None
    tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as f_in:
            f_in.write(media_bytes)
            tmp_in = f_in.name

        has_audio = False
        if shutil.which("ffprobe"):
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    tmp_in,
                ],
                capture_output=True, timeout=30,
            )
            has_audio = bool(probe.stdout.strip())

        if ext == "mp4" and has_audio:
            return media_bytes

        tmp_out = tmp_in + ".out.mp4"

        def build(copy_video: bool):
            cmd = ["ffmpeg", "-y", "-i", tmp_in]
            if not has_audio:
                cmd += [
                    "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-shortest",
                ]
            cmd += ["-movflags", "+faststart"]
            if copy_video:
                cmd += ["-c:v", "copy"]
            else:
                cmd += [
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                ]
            cmd += ["-c:a", "aac", tmp_out]
            return cmd

        result = None
        if ext in ("mp4", "mov", "mkv"):
            result = subprocess.run(build(True), capture_output=True, timeout=120)
        if result is None or result.returncode != 0:
            result = subprocess.run(build(False), capture_output=True, timeout=120)

        if result.returncode != 0:
            return media_bytes if ext == "mp4" else None

        with open(tmp_out, "rb") as f:
            return f.read()
    except Exception as e:
        logger.error(f"[Media] make_streamable_mp4 error: {e}")
        return media_bytes if ext == "mp4" else None
    finally:
        for p in (tmp_in, tmp_out):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

async def auto_delete_later(bot: Bot, chat_id: int, message_ids: List[int], delay: int):
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass

async def send_posts(
    bot: Bot,
    chat_id: int,
    posts: List[Dict],
    requested_tags: str,
    count: int = 1,
    reply_to_message_id: Optional[int] = None
) -> int:
    if not posts:
        return 0

    import random
    random.shuffle(posts)

    tag_key = requested_tags.strip() if requested_tags.strip() else "random"
    sent_count = 0
    sent_msg_ids = []
    caption = "🔞 <b>Найден пост!</b>"

    for post in posts:
        if sent_count >= count:
            break

        file_url = post.get("file_url")
        post_id = str(post.get("id", ""))
        source = post.get("source", "")

        if not file_url or recent_tracker.is_recent(tag_key, post_id):
            continue

        file_ext = file_url.lower().split('?')[0].split('.')[-1]
        is_video = file_ext in ['mp4', 'webm', 'gif', 'mov', 'avi', 'mkv']
        spoiler = config.is_spoiler_media(chat_id)

        sent_msg = None
        try:
            # Если Pixiv, изображение нужно скачать с реферером
            if source == "pixiv" or "pximg.net" in file_url:
                raw_bytes = await pixiv_service.download_image(file_url)
                if not raw_bytes:
                    continue
                input_file = BufferedInputFile(raw_bytes, filename=f"{post_id or 'pixiv'}.jpg")
                sent_msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=caption,
                    parse_mode="HTML",
                    has_spoiler=spoiler,
                    reply_to_message_id=reply_to_message_id
                )
            elif is_video:
                # Видео Rule34 / Danbooru: быстрый путь отправки по прямому URL
                try:
                    sent_msg = await bot.send_video(
                        chat_id=chat_id,
                        video=file_url,
                        caption=caption,
                        parse_mode="HTML",
                        has_spoiler=spoiler,
                        supports_streaming=True,
                        reply_to_message_id=reply_to_message_id
                    )
                except Exception as direct_err:
                    logger.debug(f"[Media] Direct video URL failed, falling back to download: {direct_err}")
                    raw_bytes = await download_file(file_url)
                    if raw_bytes:
                        processed_bytes = await asyncio.to_thread(make_streamable_mp4_sync, raw_bytes, file_ext)
                        video_data = processed_bytes or raw_bytes
                        input_file = BufferedInputFile(video_data, filename=f"{post_id or 'video'}.mp4")
                        sent_msg = await bot.send_video(
                            chat_id=chat_id,
                            video=input_file,
                            caption=caption,
                            parse_mode="HTML",
                            has_spoiler=spoiler,
                            supports_streaming=True,
                            reply_to_message_id=reply_to_message_id
                        )
            else:
                # Картинка Rule34 / Danbooru: быстрый путь отправки по прямому URL
                try:
                    sent_msg = await bot.send_photo(
                        chat_id=chat_id,
                        photo=file_url,
                        caption=caption,
                        parse_mode="HTML",
                        has_spoiler=spoiler,
                        reply_to_message_id=reply_to_message_id
                    )
                except Exception as direct_err:
                    logger.debug(f"[Media] Direct photo URL failed, falling back to download: {direct_err}")
                    raw_bytes = await download_file(file_url)
                    if raw_bytes:
                        input_file = BufferedInputFile(raw_bytes, filename=f"{post_id or 'image'}.{file_ext}")
                        sent_msg = await bot.send_photo(
                            chat_id=chat_id,
                            photo=input_file,
                            caption=caption,
                            parse_mode="HTML",
                            has_spoiler=spoiler,
                            reply_to_message_id=reply_to_message_id
                        )

            if sent_msg:
                sent_count += 1
                sent_msg_ids.append(sent_msg.message_id)
                recent_tracker.add(tag_key, post_id)

        except Exception as e:
            logger.error(f"[Media] Failed sending post {post_id}: {e}")
            continue

    if sent_count > 0 and config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
        asyncio.create_task(auto_delete_later(bot, chat_id, sent_msg_ids, config.get_auto_delete_delay(chat_id)))

    return sent_count

async def send_pixiv_manga(
    bot: Bot,
    chat_id: int,
    tags: str,
    reply_to_message_id: Optional[int] = None
) -> bool:
    album = await pixiv_service.create_manga_album(tags, config.get_pixiv_manga_max_pages(chat_id))
    if not album or not album.get("pages"):
        return False

    pages = album["pages"]
    title = album.get("title", "Pixiv Manga")
    caption = f"📖 <b>{title}</b> ({len(pages)} стр.)"

    media_group = []
    for idx, page_bytes in enumerate(pages):
        inp = BufferedInputFile(page_bytes, filename=f"page_{idx + 1}.jpg")
        media = InputMediaPhoto(
            media=inp,
            caption=caption if idx == 0 else None,
            parse_mode="HTML" if idx == 0 else None,
            has_spoiler=config.is_spoiler_media(chat_id)
        )
        media_group.append(media)

    try:
        sent_messages = await bot.send_media_group(
            chat_id=chat_id,
            media=media_group,
            reply_to_message_id=reply_to_message_id
        )
        if sent_messages and config.is_auto_delete(chat_id) and config.get_auto_delete_delay(chat_id) > 0:
            mids = [m.message_id for m in sent_messages]
            asyncio.create_task(auto_delete_later(bot, chat_id, mids, config.get_auto_delete_delay(chat_id)))
        return True
    except Exception as e:
        logger.error(f"[Media] Error sending manga album: {e}")
        return False
