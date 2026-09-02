import io
import time
import random
import logging
import asyncio
from typing import List, Dict, Optional
import requests
import config
from database import db
from utils.recent import recent_tracker

logger = logging.getLogger(__name__)

class PixivService:
    def __init__(self):
        self._api = None
        self._token_cached = ""
        self._auth_at = 0.0
        self.access_ttl = 3000
        self._lock = asyncio.Lock()

    def get_refresh_token(self) -> str:
        # Приоритет: база данных -> config (.env)
        db_token = db.get_pixiv_token()
        return db_token or config.PIXIV_REFRESH_TOKEN

    def _reset_api(self):
        self._api = None
        self._token_cached = ""
        self._auth_at = 0.0

    def _ensure_api_sync(self, force_refresh: bool = False):
        from pixivpy3 import AppPixivAPI

        token = self.get_refresh_token()
        if not token:
            raise ValueError("pixiv_token_missing")

        now = time.time()
        auth_expired = (now - self._auth_at) >= self.access_ttl
        need_auth = (
            force_refresh
            or self._api is None
            or self._token_cached != token
            or auth_expired
        )

        if not need_auth:
            return self._api

        if self._api is None:
            self._api = AppPixivAPI(timeout=30)

        last_error = None
        for attempt in range(3):
            try:
                self._api.auth(refresh_token=token)
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(f"[Pixiv] Auth attempt {attempt + 1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))

        if last_error:
            raise last_error

        new_refresh = getattr(self._api, "refresh_token", None)
        if new_refresh and new_refresh != token:
            db.set_pixiv_token(new_refresh)

        self._token_cached = self.get_refresh_token()
        self._auth_at = now
        return self._api

    @staticmethod
    def _validate_result(result):
        if result is None:
            raise ValueError("pixiv_empty_response")
        if isinstance(result, dict) and (result.get("error") or result.get("has_error")):
            raise ValueError(f"pixiv_api_error: {result.get('error', result)}")
        for attr in ("error", "has_error", "errors"):
            if getattr(result, attr, None):
                raise ValueError(f"pixiv_api_error: {getattr(result, attr)}")

    @staticmethod
    def _image_urls_to_url(image_urls) -> Optional[str]:
        if not image_urls:
            return None
        if isinstance(image_urls, dict):
            return (
                image_urls.get("large")
                or image_urls.get("medium")
                or image_urls.get("original")
                or image_urls.get("square_medium")
            )
        return (
            getattr(image_urls, "large", None)
            or getattr(image_urls, "medium", None)
            or getattr(image_urls, "original", None)
            or getattr(image_urls, "square_medium", None)
        )

    @classmethod
    def _illust_url(cls, illust) -> Optional[str]:
        meta_pages = getattr(illust, "meta_pages", None) or []
        if meta_pages:
            urls = meta_pages[0].get("image_urls") if isinstance(meta_pages[0], dict) else getattr(meta_pages[0], "image_urls", None)
            return cls._image_urls_to_url(urls)
        return cls._image_urls_to_url(getattr(illust, "image_urls", None))

    @classmethod
    def _all_page_urls(cls, illust) -> List[str]:
        urls = []
        meta_pages = getattr(illust, "meta_pages", None) or []
        for page in meta_pages:
            image_urls = page.get("image_urls") if isinstance(page, dict) else getattr(page, "image_urls", None)
            url = cls._image_urls_to_url(image_urls)
            if url and not url.lower().endswith(".zip"):
                urls.append(url)
        if not urls:
            single = cls._illust_url(illust)
            if single:
                urls.append(single)
        return urls

    def _search_sync(
        self,
        tags: str,
        limit: int,
        r18_only: bool = False,
        manga_only: bool = False,
        video_only: bool = False,
        max_pages: int = 2
    ) -> List[Dict]:
        api = self._ensure_api_sync()
        word = tags.strip() if tags else ("うごイラ" if video_only else "1girl")

        prefix = "pixiv_r18" if r18_only else ("pixiv_manga" if manga_only else "pixiv")
        tag_key = f"{prefix}_{word}" if word else f"{prefix}_random"

        posts = []
        next_qs = {
            "word": word,
            "search_target": "partial_match_for_tags",
            "sort": "date_desc",
        }
        pages = 0
        api_max_pages = 4 if manga_only else max_pages

        while next_qs and len(posts) < limit and pages < api_max_pages:
            pages += 1
            result = api.search_illust(**next_qs)
            self._validate_result(result)

            illusts = getattr(result, "illusts", None) or []
            if not illusts and isinstance(result, dict):
                illusts = result.get("illusts", [])

            for illust in illusts:
                if len(posts) >= limit:
                    break

                post_id = str(getattr(illust, "id", "") or "")
                if post_id and recent_tracker.is_recent(tag_key, post_id):
                    continue

                illust_type = getattr(illust, "type", "") or ""
                x_restrict = int(getattr(illust, "x_restrict", 0) or 0)

                if r18_only and x_restrict < 1:
                    continue
                if not r18_only and x_restrict >= 1:
                    continue

                if manga_only:
                    if illust_type != "manga":
                        continue
                    if int(getattr(illust, "page_count", 1) or 1) < 2:
                        continue

                if video_only and illust_type != "ugoira":
                    continue

                file_url = self._illust_url(illust)
                if not file_url or file_url.lower().endswith(".zip"):
                    continue

                raw_tags = getattr(illust, "tags", None) or []
                tags_list = raw_tags.split() if isinstance(raw_tags, str) else [t.get("name", "") if isinstance(t, dict) else getattr(t, "name", str(t)) for t in raw_tags]

                posts.append({
                    "id": post_id,
                    "file_url": file_url,
                    "tags": tags_list,
                    "rating": str(x_restrict),
                    "title": getattr(illust, "title", "") or "",
                    "page_count": int(getattr(illust, "page_count", 1) or 1),
                    "source": "pixiv"
                })

            if len(posts) >= limit:
                break
            next_qs = api.parse_qs(getattr(result, "next_url", None))
            if not illusts:
                break

        return posts

    async def search(
        self,
        tags: str,
        limit: int = 10,
        r18_only: bool = False,
        manga_only: bool = False,
        video_only: bool = False
    ) -> List[Dict]:
        if not self.get_refresh_token():
            logger.warning("[Pixiv] refresh_token не установлен")
            return []

        def _run():
            for attempt in range(3):
                try:
                    return self._search_sync(
                        tags=tags,
                        limit=limit,
                        r18_only=r18_only,
                        manga_only=manga_only,
                        video_only=video_only
                    )
                except Exception as e:
                    logger.error(f"[Pixiv] Search attempt {attempt + 1} failed: {e}")
                    self._reset_api()
                    if attempt < 2:
                        try:
                            self._ensure_api_sync(force_refresh=True)
                        except Exception:
                            pass
            return []

        return await asyncio.to_thread(_run)

    async def download_image(self, url: str) -> Optional[bytes]:
        import aiohttp
        headers = config.get_request_headers()
        headers["Referer"] = config.PIXIV_REFERER
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) >= 128 and not data[:256].lower().startswith((b"<!doctype", b"<html")):
                            return data
        except Exception as e:
            logger.error(f"[Pixiv] async download failed for {url}: {e}")
        return None

    def _get_manga_candidate_sync(self, tags: str, max_pages: int) -> Optional[Dict]:
        candidates = self._search_sync(
            tags=tags,
            limit=30,
            max_pages=4,
            manga_only=True,
            r18_only=True
        )
        if not candidates:
            return None

        random.shuffle(candidates)
        api = self._ensure_api_sync()
        tag_key = f"pixiv_manga_r18_{tags.strip()}" if tags.strip() else "pixiv_manga_r18_random"

        for candidate in candidates:
            post_id = candidate.get("id", "")
            if post_id and recent_tracker.is_recent(tag_key, post_id):
                continue

            try:
                detail = api.illust_detail(post_id)
                self._validate_result(detail)
                illust = getattr(detail, "illust", None)
                if not illust or int(getattr(illust, "x_restrict", 0) or 0) < 1:
                    continue

                page_urls = self._all_page_urls(illust)
                if len(page_urls) < 2:
                    continue

                page_urls = page_urls[:max_pages]
                title = (getattr(illust, "title", None) or tags or "Pixiv Manga").strip()
                recent_tracker.add(tag_key, post_id)

                return {
                    "title": title,
                    "urls": page_urls,
                    "id": post_id
                }
            except Exception as e:
                logger.error(f"[Pixiv] Manga detail error {post_id}: {e}")
        return None

    async def create_manga_album(self, tags: str, max_pages: int = 40) -> Optional[Dict]:
        info = await asyncio.to_thread(self._get_manga_candidate_sync, tags, max_pages)
        if not info or not info.get("urls"):
            return None

        urls = info["urls"]
        sem = asyncio.Semaphore(10)

        async def fetch_page(u: str) -> Optional[bytes]:
            async with sem:
                return await self.download_image(u)

        tasks = [fetch_page(u) for u in urls]
        results = await asyncio.gather(*tasks)
        pages_data = [r for r in results if r is not None]

        if len(pages_data) < 2:
            return None

        return {
            "title": info["title"],
            "pages": pages_data,
            "id": info["id"],
        }

pixiv_service = PixivService()
