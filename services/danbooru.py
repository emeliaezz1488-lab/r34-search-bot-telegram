import logging
import aiohttp
from typing import List, Dict
import config
from utils.recent import recent_tracker

logger = logging.getLogger(__name__)

class DanbooruService:
    def __init__(self):
        self.url = "https://danbooru.donmai.us/posts.json"

    async def search(self, tags: str, limit: int = 100) -> List[Dict]:
        query_parts = tags.split() if tags else []
        include_tags = [p for p in query_parts if not p.startswith('-')]
        search_tags = ' '.join(include_tags).strip()

        params = {
            'limit': min(limit, 20),
        }
        if search_tags:
            params['tags'] = search_tags

        headers = {
            "User-Agent": "Rule34Searcher/1.0 (by DubstepNamaz on Danbooru)",
            "Accept": "application/json",
        }
        auth = aiohttp.BasicAuth(config.DANBOORU_USER, config.DANBOORU_API_KEY)

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.url, params=params, headers=headers, auth=auth) as response:
                    if response.status != 200:
                        logger.error(f"[Danbooru] HTTP error {response.status}")
                        return []
                    data = await response.json()
        except Exception as e:
            logger.error(f"[Danbooru] Request failed: {e}")
            return []

        if not isinstance(data, list):
            return []

        posts = []
        tag_key = f"danbooru_{search_tags}" if search_tags else "danbooru_random"

        for post in data:
            post_id = str(post.get("id", ""))
            if not post_id or recent_tracker.is_recent(tag_key, post_id):
                continue

            image_url = post.get('file_url') or post.get('large_file_url') or post.get('preview_file_url')
            if not image_url:
                continue

            tag_string = post.get('tag_string', '')
            tags_list = tag_string.split() if tag_string else []

            posts.append({
                "id": post_id,
                "file_url": image_url,
                "tags": tags_list,
                "rating": post.get("rating", ""),
                "source": "danbooru"
            })

        return posts

danbooru_service = DanbooruService()
