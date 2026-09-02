import asyncio
import logging
from collections import defaultdict
from typing import Set, Dict

logger = logging.getLogger(__name__)

class TaskTracker:
    def __init__(self):
        self._tasks: Dict[int, Set[asyncio.Task]] = defaultdict(set)
        self._lock = asyncio.Lock()

    def add_task(self, chat_id: int, task: asyncio.Task):
        if task:
            self._tasks[chat_id].add(task)

    def remove_task(self, chat_id: int, task: asyncio.Task):
        if task and chat_id in self._tasks:
            self._tasks[chat_id].discard(task)
            if not self._tasks[chat_id]:
                del self._tasks[chat_id]

    def cancel_chat_tasks(self, chat_id: int) -> int:
        tasks = list(self._tasks.get(chat_id, set()))
        cancelled_count = 0
        for task in tasks:
            if not task.done():
                task.cancel()
                cancelled_count += 1
        if chat_id in self._tasks:
            del self._tasks[chat_id]
        return cancelled_count

    def get_active_tasks_count(self, chat_id: int) -> int:
        tasks = self._tasks.get(chat_id, set())
        return sum(1 for t in tasks if not t.done())

task_tracker = TaskTracker()

class TrackChatTask:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.task = None

    async def __aenter__(self):
        self.task = asyncio.current_task()
        if self.task:
            task_tracker.add_task(self.chat_id, self.task)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.task:
            task_tracker.remove_task(self.chat_id, self.task)
