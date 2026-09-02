import random
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import aiohttp
import config
from utils.recent import recent_tracker

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

    async def search(self, tags: str, limit: int = 100, antiai: bool = True) -> List[Dict]:
        search_tags = self._prepare_tags(tags, antiai=antiai)
        random_page = random.randint(0, 10)

        params = {
            'page': 'dapi',
            's': 'post',
            'q': 'index',
            'limit': min(limit, 1000),
            'pid': random_page,
            'api_key': config.R34_API_KEY,
            'user_id': config.R34_USER_ID,
        }
        if search_tags:
            params['tags'] = search_tags

        headers = config.get_request_headers()

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.url, params=params, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"[Rule34] HTTP error: {response.status}")
                        return []
                    text = await response.text()
        except Exception as e:
            logger.error(f"[Rule34] Request failed: {e}")
            return []

        try:
            root = ET.fromstring(text)
            posts = []
            tag_key = f"r34_{search_tags}" if search_tags else "r34_random"

            for post in root.findall("post"):
                post_id = post.get("id", "")
                if not post_id or recent_tracker.is_recent(tag_key, post_id):
                    continue

                image_url = post.get('file_url') or post.get('sample_url')
                if not image_url:
                    continue

                tags_str = post.get('tags', '')
                tags_list = tags_str.split() if tags_str else []

                posts.append({
                    "id": post_id,
                    "file_url": image_url,
                    "tags": tags_list,
                    "rating": post.get("rating", ""),
                    "source": "rule34"
                })

            return posts
        except Exception as e:
            logger.error(f"[Rule34] XML parse error: {e}")
            return []

rule34_service = Rule34Service()
