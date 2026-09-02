import time
import asyncio
from collections import defaultdict, deque
import config

class AntiSpam:
    def __init__(
        self,
        spam_limit: int = 3,
        spam_window: int = 3,
        block_duration: int = 15,
        global_limit: int = 10,
        global_window: int = 10
    ):
        self.spam_limit = spam_limit
        self.spam_window = spam_window
        self.block_duration = block_duration
        self.global_limit = global_limit
        self.global_window = global_window

        self._spam_events = defaultdict(deque)
        self._chat_spam_events = defaultdict(deque)
        self._spam_blocks = {}
        self._chat_spam_blocks = {}
        self._spam_lock = asyncio.Lock()

    def _prune(self, events: deque, current_time: float, window: int):
        while events and current_time - events[0] > window:
            events.popleft()

    def _is_blocked(self, blocks: dict, key: str, current_time: float) -> bool:
        until = blocks.get(key)
        if not until:
            return False
        if current_time < until:
            return True
        del blocks[key]
        return False

    async def is_spam(self, user_id: int, chat_id: int) -> bool:
        if not config.is_spam_protection(chat_id):
            return False

        current_time = time.time()
        user_key = f"{user_id}:{chat_id}"
        chat_key = str(chat_id)

        async with self._spam_lock:
            if self._is_blocked(self._chat_spam_blocks, chat_key, current_time):
                return True
            if self._is_blocked(self._spam_blocks, user_key, current_time):
                return True

            user_events = self._spam_events[user_key]
            chat_events = self._chat_spam_events[chat_key]

            self._prune(user_events, current_time, self.spam_window)
            self._prune(chat_events, current_time, self.global_window)

            if len(user_events) >= self.spam_limit:
                self._spam_blocks[user_key] = current_time + self.block_duration
                user_events.clear()
                return True

            if len(chat_events) >= self.global_limit:
                self._chat_spam_blocks[chat_key] = current_time + self.block_duration
                chat_events.clear()
                return True

            user_events.append(current_time)
            chat_events.append(current_time)
            return False

antispam = AntiSpam()
