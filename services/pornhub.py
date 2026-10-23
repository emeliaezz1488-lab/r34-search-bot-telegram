import re
import time
import logging
from typing import List, Dict, Optional
import asyncio
import requests
from bs4 import BeautifulSoup
import config
from utils.recent import recent_tracker

logger = logging.getLogger("pornhub")

class PornhubService:
    """
    Высокопроизводительный сервис поиска и парсинга Pornhub.
    Работает через сессионный скрапер с обходом защиты OpenResty/Cloudflare
    (сохранение сессионных кук rp/ua/bs, cookies возраста и выбор зеркал).
    """
    BASE_DOMAINS = ["rt.pornhub.com", "www.pornhub.com"]

    def __init__(self):
        self._session: Optional[requests.Session] = None
        self._last_init_time: float = 0
        self._active_domain = self.BASE_DOMAINS[0]

    def _get_session(self) -> requests.Session:
        now = time.time()
        if self._session is None or (now - self._last_init_time > 1800):
            s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            })
            for domain in self.BASE_DOMAINS:
                try:
                    logger.info(f"[Pornhub] Инициализация сессии на https://{domain}/...")
                    r = s.get(f"https://{domain}/", timeout=10)
                    if r.status_code == 200:
                        s.cookies.set("age_verified", "1", domain=".pornhub.com")
                        s.cookies.set("platform", "pc", domain=".pornhub.com")
                        s.cookies.set("accessAgeDisclaimerPH", "1", domain=".pornhub.com")
                        self._active_domain = domain
                        self._session = s
                        self._last_init_time = now
                        logger.info(f"✅ [Pornhub] Сессия успешно активирована через {domain}")
                        return self._session
                except Exception as e:
                    logger.warning(f"[Pornhub] Не удалось инициализировать сессию на {domain}: {e}")

            # Fallback
            self._session = s
            self._last_init_time = now
        return self._session

    def _sync_search(self, query: str, limit: int = 20, ordering: str = "mostviewed") -> List[Dict]:
        session = self._get_session()
        search_query = query.strip()

        order_map = {
            "mostviewed": "mv",
            "rating": "tr",
            "newest": "mr",
            "featured": "fe"
        }
        o_param = order_map.get(ordering, "mv")

        params = {}
        if search_query:
            params["search"] = search_query
            params["o"] = o_param
        else:
            params["o"] = o_param

        url = f"https://{self._active_domain}/video/search"

        try:
            resp = session.get(url, params=params, timeout=12)
            if resp.status_code != 200:
                logger.warning(f"[Pornhub] Поиск вернул статус {resp.status_code} на {self._active_domain}, сбрасываем сессию...")
                self._session = None
                return []
            html = resp.text
        except Exception as e:
            logger.error(f"[Pornhub] Ошибка сетевого запроса поиска: {e}")
            self._session = None
            return []

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select("li[data-video-vkey], li.videoBox, div.videoBox")
        if not items:
            logger.warning(f"[Pornhub] Карточки видео не найдены на странице (длина HTML: {len(html)})")
            return []

        tag_key = f"pornhub_{search_query}" if search_query else "pornhub_top"
        posts = []
        seen_keys = set()

        for item in items:
            vkey = item.get("data-video-vkey")
            if not vkey:
                link_el = item.select_one("a[href*='viewkey=']")
                if link_el:
                    href = link_el.get("href", "")
                    if "viewkey=" in href:
                        vkey = href.split("viewkey=")[-1].split("&")[0]

            if not vkey or vkey in seen_keys:
                continue
            seen_keys.add(vkey)

            if recent_tracker.is_recent(tag_key, vkey):
                continue

            title_el = item.select_one(".title a, a[title]")
            title = ""
            if title_el:
                title = title_el.get("title") or title_el.text.strip()
            if not title:
                title = f"Pornhub Video {vkey}"

            img_el = item.select_one("img")
            thumb = ""
            if img_el:
                thumb = (
                    img_el.get("data-thumb_url")
                    or img_el.get("data-src")
                    or img_el.get("data-mediumthumb")
                    or img_el.get("src")
                    or ""
                )

            dur_el = item.select_one(".duration, var.duration")
            duration = dur_el.text.strip() if dur_el else ""

            views_el = item.select_one(".views var, .views")
            views = views_el.text.strip() if views_el else ""

            rating_el = item.select_one(".value")
            rating = rating_el.text.strip() if rating_el else ""

            web_url = f"https://www.pornhub.com/view_video.php?viewkey={vkey}"

            posts.append({
                "id": vkey,
                "title": title,
                "file_url": thumb,
                "thumb_url": thumb,
                "web_url": web_url,
                "duration": duration,
                "views": views,
                "rating": rating,
                "tags": [search_query] if search_query else [],
                "source": "pornhub"
            })

            if len(posts) >= limit:
                break

        logger.info(f"✅ [Pornhub] Успешно спарсено {len(posts)} видео по запросу '{search_query}'")
        return posts

    async def search(self, query: str = "", limit: int = 20, ordering: str = "mostviewed") -> List[Dict]:
        """
        Асинхронный поиск видео по запросу без блокировки event-loop.
        """
        return await asyncio.to_thread(self._sync_search, query, limit, ordering)

pornhub_service = PornhubService()

