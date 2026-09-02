import os
import random
from pathlib import Path
from dotenv import load_dotenv
from database import db

# Загрузка переменных окружения из .env файла
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Пытаемся прочитать токен Pixiv из ../token.txt если не задан в .env
token_txt_path = BASE_DIR.parent / "token.txt"
default_pixiv_token = ""
if token_txt_path.exists():
    try:
        default_pixiv_token = token_txt_path.read_text(encoding="utf-8").strip()
    except Exception:
        pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PIXIV_REFRESH_TOKEN = os.getenv("PIXIV_REFRESH_TOKEN", default_pixiv_token).strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6869409295"))

# Статические API данные
R34_API_KEY = "d82f6db279ce94313e629e791533d456a4309dfeb528ddab6eee4b7472156f0def07ebfd3e64b9dddbf0d3b78f227ba8a5f386533ef1ccb1377d8a97481811dc"
R34_USER_ID = "5255009"
DANBOORU_USER = "DubstepNamaz"
DANBOORU_API_KEY = "5qAAyDRZ22DFp8thwVXqGrfk"
PIXIV_REFERER = "https://www.pixiv.net/"

POSTS_COUNT = int(os.getenv("POSTS_COUNT", "100"))

# Динамические настройки per-chat (сохраняются индивидуально для каждого чата/группы)
def is_triggers_enabled(chat_id: int = 0) -> bool:
    return bool(db.get_chat_setting(chat_id, "triggers_enabled", True))

def get_default_source(chat_id: int = 0) -> str:
    return str(db.get_chat_setting(chat_id, "default_source", "rule34")).lower()

def is_spoiler_media(chat_id: int = 0) -> bool:
    return bool(db.get_chat_setting(chat_id, "spoiler_media", True))

def is_auto_delete(chat_id: int = 0) -> bool:
    return bool(db.get_chat_setting(chat_id, "auto_delete", True))

def get_auto_delete_delay(chat_id: int = 0) -> int:
    return int(db.get_chat_setting(chat_id, "auto_delete_delay", 30))

def is_antiai(chat_id: int = 0) -> bool:
    return bool(db.get_chat_setting(chat_id, "antiai", True))

def is_spam_protection(chat_id: int = 0) -> bool:
    return bool(db.get_chat_setting(chat_id, "spam_protection", True))

def get_send_count(chat_id: int = 0) -> int:
    return int(db.get_chat_setting(chat_id, "send_count", 1))

def get_pixiv_manga_max_pages(chat_id: int = 0) -> int:
    return int(db.get_chat_setting(chat_id, "pixiv_manga_max_pages", 40))

# Список User-Agent для ротации
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)

def get_request_headers(rotate_ua: bool = True) -> dict:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if rotate_ua:
        headers["User-Agent"] = get_random_user_agent()
    else:
        headers["User-Agent"] = USER_AGENTS[0]
    return headers
