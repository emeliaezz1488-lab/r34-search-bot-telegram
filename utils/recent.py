from collections import defaultdict, deque

class RecentTracker:
    def __init__(self, maxlen: int = 50):
        self.maxlen = maxlen
        self._recent = defaultdict(lambda: deque(maxlen=self.maxlen))

    def is_recent(self, tag_key: str, post_id: str) -> bool:
        return str(post_id) in self._recent[tag_key]

    def add(self, tag_key: str, post_id: str):
        if post_id:
            self._recent[tag_key].append(str(post_id))

recent_tracker = RecentTracker()
