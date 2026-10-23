import asyncio
import logging
from typing import Optional, Dict
import aiohttp
import config

logger = logging.getLogger("http_client")

_session: Optional[aiohttp.ClientSession] = None
_lock = asyncio.Lock()

async def get_http_session() -> aiohttp.ClientSession:
    """
    Возвращает единую глобальную сессию aiohttp с пулом соединений,
    кэшированием DNS и keep-alive. Это устраняет задержки на повторные TLS handshake
    и ускоряет загрузку медиа и работу API на VDS в разы.
    """
    global _session
    if _session is None or _session.closed:
        async with _lock:
            if _session is None or _session.closed:
                timeout = aiohttp.ClientTimeout(total=60, connect=10)
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=20,
                    ttl_dns_cache=300,
                    keepalive_timeout=75,
                    enable_cleanup_closed=True
                )
                _session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector
                )
    return _session

async def close_http_session():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None

async def fast_download(url: str, referer: Optional[str] = None) -> Optional[bytes]:
    """
    Высокоскоростная загрузка файла через постоянный пул соединений.
    """
    headers = config.get_request_headers()
    if referer:
        headers["Referer"] = referer
    elif "pixiv.net" in url or "pximg.net" in url:
        headers["Referer"] = config.PIXIV_REFERER
    elif "rule34.xxx" in url:
        headers["Referer"] = "https://rule34.xxx/"
    elif "donmai.us" in url:
        headers["Referer"] = "https://danbooru.donmai.us/"
    elif "konachan.com" in url:
        headers["Referer"] = "https://konachan.com/"
    elif "phncdn.com" in url or "pornhub.com" in url:
        headers["Referer"] = "https://www.pornhub.com/"

    try:
        session = await get_http_session()
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.error(f"[FastDownload] HTTP {resp.status} для {url[:80]}")
    except Exception as e:
        logger.error(f"[FastDownload] Ошибка загрузки {url[:80]}: {e}")
    return None
