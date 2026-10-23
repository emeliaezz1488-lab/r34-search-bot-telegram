import logging
from typing import List, Dict
import config
from utils.recent import recent_tracker
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

# Маппинг популярных тегов на специфичные теги Konachan (Moebooru)
KONA_TAG_ALIASES = {
    "femboy": "trap",
    "femboys": "trap",
    "1girl": "female",
    "1boy": "male",
    "фембой": "trap",
    "фембои": "trap",
    "трап": "trap",
    "трапы": "trap",
    "фута": "futanari",
    "футанари": "futanari",
    "тян": "female",
    "девушка": "female",
    "лоли": "loli",
    "милфа": "milf",
    "юри": "yuri",
    "аниме": "anime",
    "хентай": "rating:e",
    "порно": "rating:e",
    "видео": "animated",
    "гиф": "animated",
}

class KonachanService:
    def __init__(self):
        self.url = "https://konachan.com/post.json"

    async def search(self, tags: str = "", limit: int = 100, rating_explicit: bool = False) -> List[Dict]:
        raw_words = tags.strip().split() if tags else []
        mapped_words = [KONA_TAG_ALIASES.get(w.lower(), w) for w in raw_words]

        # Если нужен явный 18+, добавляем rating:e если ещё нет фильтра рейтинга
        if rating_explicit and not any(w.startswith("rating:") for w in mapped_words):
            mapped_words.append("rating:e")

        # Для разнообразия добавляем order:random если не указана другая сортировка
        if not any(w.startswith("order:") for w in mapped_words):
            mapped_words.append("order:random")

        search_tags = " ".join(mapped_words).strip()

        params = {
            "limit": min(max(limit, 10), 100),
        }
        if search_tags:
            params["tags"] = search_tags

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://konachan.com/",
        }

        try:
            session = await get_http_session()
            async with session.get(self.url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"[Konachan] HTTP error {response.status}")
                    return []
                data = await response.json()
        except Exception as e:
            logger.error(f"[Konachan] Request failed: {e}")
            return []

        if not isinstance(data, list):
            return []

        posts = []
        tag_key = f"konachan_{search_tags}" if search_tags else "konachan_random"

        for post in data:
            post_id = str(post.get("id", ""))
            if not post_id or recent_tracker.is_recent(tag_key, post_id):
                continue

            file_url = post.get("file_url") or ""
            sample_url = post.get("sample_url") or ""
            jpeg_url = post.get("jpeg_url") or ""
            file_ext = file_url.lower().split("?")[0].split(".")[-1]

            # Для GIF и видео берем оригинальный файл
            is_animated = file_ext in ["gif", "webm", "mp4"]

            # Для картинок предпочитаем sample_url (быстрый веб-формат 1500px), затем jpeg_url / file_url
            if is_animated:
                target_url = file_url
            else:
                target_url = sample_url or jpeg_url or file_url

            if not target_url:
                continue

            # Превращаем относительные или schema-less ссылки в полные https://
            if target_url.startswith("//"):
                target_url = "https:" + target_url

            raw_tags = post.get("tags", "")
            tags_list = raw_tags.split() if isinstance(raw_tags, str) else []

            posts.append({
                "id": post_id,
                "file_url": target_url,
                "tags": tags_list,
                "rating": post.get("rating", "s"),
                "source": "konachan"
            })

        return posts

konachan_service = KonachanService()
