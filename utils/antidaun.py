import time
import asyncio
import logging
from collections import defaultdict
from typing import Dict, Tuple
import config

logger = logging.getLogger("antidaun")

class AntiDaunProtect:
    """
    Система защиты от злоупотреблений (Anti Daun Protect):
    - Обычные пользователи: максимум 10 медиа за раз, максимум 2 параллельных запроса.
    - Умный Rate-Limit: 1 запрос раз в 15 секунд для обычных пользователей.
    - Администраторы: без ограничений (без кулдауна и без лимитов).
    - Защита является неотключаемой системной политикой ядра.
    """
    def __init__(self, max_concurrent: int = 2, max_media: int = 10, cooldown_seconds: float = 15.0):
        self.max_concurrent = max_concurrent
        self.max_media = max_media
        self.cooldown_seconds = cooldown_seconds
        self._user_tasks: Dict[int, int] = defaultdict(int)
        self._user_last_request: Dict[int, float] = {}
        self._lock = asyncio.Lock()

    def clamp_count(self, count: int, user_id: int) -> int:
        """Ограничивает количество медиа для обычных пользователей до 10."""
        if config.is_admin(user_id):
            return max(1, count)
        return max(1, min(count, self.max_media))

    def check_rate_limit(self, user_id: int) -> Tuple[bool, float]:
        """
        Проверяет ограничение частоты (кулдаун 15 секунд).
        Возвращает (can_proceed: bool, remaining_seconds: float).
        Админы всегда получают (True, 0.0).
        """
        if config.is_admin(user_id):
            return True, 0.0
        now = time.time()
        last = self._user_last_request.get(user_id, 0.0)
        elapsed = now - last
        if elapsed < self.cooldown_seconds:
            return False, round(self.cooldown_seconds - elapsed, 1)
        return True, 0.0

    def record_request(self, user_id: int):
        """Запоминает время успешного запроса."""
        if not config.is_admin(user_id):
            self._user_last_request[user_id] = time.time()

    async def can_start(self, user_id: int) -> bool:
        if config.is_admin(user_id):
            return True
        async with self._lock:
            return self._user_tasks[user_id] < self.max_concurrent

    async def acquire(self, user_id: int) -> bool:
        if config.is_admin(user_id):
            return True
        async with self._lock:
            if self._user_tasks[user_id] >= self.max_concurrent:
                return False
            self._user_tasks[user_id] += 1
            return True

    async def release(self, user_id: int):
        if config.is_admin(user_id):
            return
        async with self._lock:
            if self._user_tasks[user_id] > 0:
                self._user_tasks[user_id] -= 1

class TrackUserTask:
    """Контекстный менеджер для учета параллельных запросов пользователя."""
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.acquired = False

    async def __aenter__(self) -> bool:
        self.acquired = await antidaun.acquire(self.user_id)
        return self.acquired

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            await antidaun.release(self.user_id)

antidaun = AntiDaunProtect()
