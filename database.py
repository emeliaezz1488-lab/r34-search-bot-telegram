import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Set, List

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent / "data.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "triggers_enabled": True,
    "default_source": "rule34",
    "spoiler_media": True,
    "auto_delete": True,
    "auto_delete_delay": 30,
    "spam_protection": True,
    "antiai": True,
    "send_count": 1,
    "pixiv_manga_max_pages": 40,
}

class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._data: Dict[str, Any] = {
            "pixiv_refresh_token": "",
            "chats_settings": {},
            "blacklist": [],
            "known_chats": {}
        }
        self.load()

    def load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    self._data["pixiv_refresh_token"] = loaded.get("pixiv_refresh_token", "")
                    self._data["chats_settings"] = loaded.get("chats_settings", {})
                    self._data["blacklist"] = loaded.get("blacklist", [])
                    self._data["known_chats"] = loaded.get("known_chats", {})
            except Exception as e:
                logger.error(f"[Database] Error reading {self.path}: {e}")

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Database] Error saving {self.path}: {e}")

    # Pixiv token
    def get_pixiv_token(self) -> str:
        return self._data.get("pixiv_refresh_token", "")

    def set_pixiv_token(self, token: str):
        self._data["pixiv_refresh_token"] = token.strip()
        self.save()

    # Per-chat settings
    def get_chat_setting(self, chat_id: int, key: str, default: Any = None) -> Any:
        cid = str(chat_id)
        chat_dict = self._data.get("chats_settings", {}).get(cid, {})
        if key in chat_dict:
            return chat_dict[key]
        if key in DEFAULT_SETTINGS:
            return DEFAULT_SETTINGS[key]
        return default

    def set_chat_setting(self, chat_id: int, key: str, value: Any):
        cid = str(chat_id)
        if "chats_settings" not in self._data:
            self._data["chats_settings"] = {}
        if cid not in self._data["chats_settings"]:
            self._data["chats_settings"][cid] = DEFAULT_SETTINGS.copy()
        self._data["chats_settings"][cid][key] = value
        self.save()

    def get_all_chat_settings(self, chat_id: int) -> Dict[str, Any]:
        cid = str(chat_id)
        settings = DEFAULT_SETTINGS.copy()
        custom = self._data.get("chats_settings", {}).get(cid, {})
        settings.update(custom)
        return settings

    # Blacklist by ID (user_id or chat_id)
    def is_blacklisted(self, entity_id: int) -> bool:
        return entity_id in self.get_blacklist()

    def get_blacklist(self) -> Set[int]:
        return set(self._data.get("blacklist", []))

    def add_to_blacklist(self, entity_id: int) -> bool:
        bl = self.get_blacklist()
        if entity_id not in bl:
            bl.add(entity_id)
            self._data["blacklist"] = list(bl)
            self.save()
            return True
        return False

    def remove_from_blacklist(self, entity_id: int) -> bool:
        bl = self.get_blacklist()
        if entity_id in bl:
            bl.remove(entity_id)
            self._data["blacklist"] = list(bl)
            self.save()
            return True
        return False

    # Known chats tracking for admin panel
    def record_chat(self, chat_id: int, title: str, chat_type: str):
        cid = str(chat_id)
        if "known_chats" not in self._data:
            self._data["known_chats"] = {}
        self._data["known_chats"][cid] = {
            "id": chat_id,
            "title": title or f"Чат {chat_id}",
            "type": str(chat_type),
            "last_active": int(time.time())
        }
        self.save()

    def get_known_chats(self) -> List[Dict[str, Any]]:
        chats = list(self._data.get("known_chats", {}).values())
        # Сортируем по недавней активности
        chats.sort(key=lambda x: x.get("last_active", 0), reverse=True)
        return chats

db = Database()
