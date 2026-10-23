import random
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Tuple
import aiohttp
import config
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

ANTI_AI_TAGS = [
    '-ai_generated', '-stable_diffusion', '-midjourney', '-artificial_intelligence',
    '-neural_network', '-machine_learning', '-deepfake', '-ai_art', '-ai-generated',
    '-generated_by_ai', '-dall_e', '-dalle', '-novelai', '-waifu_diffusion'
]

class Rule34Service:
    def __init__(self):
        self.url = "https://api.rule34.xxx/index.php"

    def _prepare_tags(self, tags: str, antiai: bool = True) -> str:
        query_parts = tags.split() if tags else []
        include_tags = []
        exclude_tags = []

        for part in query_parts:
            if part.startswith('-'):
                exclude_tags.append(part[1:])
            else:
                include_tags.append(part)

        search_tags = ' '.join(include_tags).strip()

        if antiai:
            search_tags += ' ' + ' '.join(ANTI_AI_TAGS)

        if exclude_tags:
            search_tags += ' ' + ' '.join(['-' + t for t in exclude_tags])

        return search_tags.strip()

    async def _fetch_page(self, search_tags: str, pid: int = 0, limit: int = 100) -> Tuple[List[Dict], int]:
        params = {
            'page': 'dapi',
            's': 'post',
            'q': 'index',
            'limit': min(limit, 1000),
            'pid': pid,
            'api_key': config.R34_API_KEY,
            'user_id': config.R34_USER_ID,
        }
        if search_tags:
            params['tags'] = search_tags

        headers = config.get_request_headers()

        try:
            session = await get_http_session()
            async with session.get(self.url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"[Rule34] HTTP error: {response.status}")
                    return [], 0
                text = await response.text()
        except Exception as e:
            logger.error(f"[Rule34] Request failed on pid={pid}: {e}")
            return [], 0

        try:
            root = ET.fromstring(text)
            total_count = int(root.get("count", "0"))
            posts = []

            for post in root.findall("post"):
                post_id = post.get("id", "")
                if not post_id:
                    continue

                raw_file_url = post.get('file_url') or ""
                sample_url = post.get('sample_url') or ""

                file_ext = raw_file_url.lower().split('?')[0].split('.')[-1]
                is_video = file_ext in ['mp4', 'webm', 'gif', 'mov', 'avi', 'mkv']

                # Для картинок берем sample_url (100-300 КБ вместо 10-30 МБ) для молниеносной отправки
                if not is_video and sample_url:
                    target_url = sample_url
                else:
                    target_url = raw_file_url or sample_url

                if not target_url:
                    continue

                tags_str = post.get('tags', '')
                tags_list = tags_str.split() if tags_str else []

                posts.append({
                    "id": post_id,
                    "file_url": target_url,
                    "tags": tags_list,
                    "rating": post.get("rating", ""),
                    "source": "rule34"
                })

            return posts, total_count
        except Exception as e:
            logger.error(f"[Rule34] XML parse error on pid={pid}: {e}")
            return [], 0

    async def search(self, tags: str, limit: int = 100, antiai: bool = True) -> List[Dict]:
        search_tags = self._prepare_tags(tags, antiai=antiai)

        # Мгновенный запрос первой страницы (дает до 100 постов за один быстрый HTTP-запрос)
        posts, total_count = await self._fetch_page(search_tags, pid=0, limit=limit)

        # Если ничего не нашлось с anti-ai тегами, пробуем без них
        if not posts and antiai:
            logger.debug(f"[Rule34] Поиск по '{tags}' не дал результатов с anti-ai, пробуем без него...")
            raw_tags = self._prepare_tags(tags, antiai=False)
            posts, total_count = await self._fetch_page(raw_tags, pid=0, limit=limit)

        return posts

rule34_service = Rule34Service()
