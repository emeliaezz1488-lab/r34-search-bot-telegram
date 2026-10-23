import os
import json
import sqlite3
import logging
import time
import threading
from pathlib import Path
from typing import Any, Dict, Set, List, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DB_FILE = BASE_DIR / "bot_database.db"
JSON_BACKUP = BASE_DIR / "data.json"

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
    "media_filter": "all",
}

class Database:
    """
    Универсальная база данных с поддержкой MariaDB / MySQL и SQLite fallback.
    - Мгновенный in-memory кэш (0 мс доступ).
    - Если в .env заданы DB_HOST / DB_USER / DB_NAME — используется MariaDB.
    - Если параметры не заданы или MariaDB недоступна — автоматический fallback на SQLite (bot_database.db).
    - Фоновый бэкап в data.json.
    """
    def __init__(self, db_path: Path = DB_FILE, json_path: Path = JSON_BACKUP):
        self.db_path = db_path
        self.json_path = json_path
        self._lock = threading.Lock()

        # Параметры подключения к MariaDB / MySQL
        self.db_host = os.getenv("DB_HOST", "").strip()
        self.db_port = int(os.getenv("DB_PORT", "3306").strip() or 3306)
        self.db_user = os.getenv("DB_USER", "").strip()
        self.db_pass = os.getenv("DB_PASSWORD", "").strip()
        self.db_name = os.getenv("DB_NAME", "nsfw_bot").strip()

        self.use_mariadb = bool(self.db_host and self.db_user)

        # In-memory кэш для мгновенных ответов
        self._chats_settings: Dict[str, Dict[str, Any]] = {}
        self._blacklist: Set[int] = set()
        self._known_chats: Dict[str, Dict[str, Any]] = {}
        self._pixiv_token: str = ""

        if self.use_mariadb:
            self._init_mariadb()
        else:
            self._init_sqlite()

        self._migrate_from_json_if_needed()
        self._load_all_to_cache()

    def _get_mariadb_conn(self):
        import pymysql
        return pymysql.connect(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_pass,
            database=self.db_name,
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=10
        )

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_mariadb(self):
        try:
            with self._get_mariadb_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS `chats_settings` (
                            `chat_id` VARCHAR(64) NOT NULL,
                            `key` VARCHAR(64) NOT NULL,
                            `value` TEXT NOT NULL,
                            PRIMARY KEY (`chat_id`, `key`)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS `known_chats` (
                            `chat_id` BIGINT NOT NULL,
                            `title` VARCHAR(255) NOT NULL DEFAULT '',
                            `type` VARCHAR(32) NOT NULL DEFAULT 'group',
                            `last_active` BIGINT NOT NULL DEFAULT 0,
                            PRIMARY KEY (`chat_id`)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS `blacklist` (
                            `entity_id` BIGINT NOT NULL,
                            PRIMARY KEY (`entity_id`)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS `bot_kv` (
                            `key` VARCHAR(64) NOT NULL,
                            `value` TEXT NOT NULL,
                            PRIMARY KEY (`key`)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                    """)
            logger.info(f"🐬 [Database] Успешное подключение к MariaDB на {self.db_host}:{self.db_port}/{self.db_name}")
        except Exception as e:
            logger.error(f"❌ [Database] Ошибка подключения к MariaDB ({e}). Переключаемся на SQLite fallback.")
            self.use_mariadb = False
            self._init_sqlite()

    def _init_sqlite(self):
        with self._lock:
            with self._get_sqlite_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chats_settings (
                        chat_id TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        PRIMARY KEY (chat_id, key)
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS known_chats (
                        chat_id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        type TEXT NOT NULL,
                        last_active INTEGER NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS blacklist (
                        entity_id INTEGER PRIMARY KEY
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS bot_kv (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                """)
                conn.commit()
            logger.info("📦 [Database] Используется локальная база SQLite (bot_database.db)")

    def _migrate_from_json_if_needed(self):
        """Миграция настроек из data.json, если база пустая."""
        if not self.json_path.exists():
            return

        with self._lock:
            has_data = False
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT COUNT(*) FROM `chats_settings`;")
                            has_data = cur.fetchone()[0] > 0
                except Exception:
                    pass
            else:
                with self._get_sqlite_conn() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM chats_settings;").fetchone()[0]
                    has_data = count > 0

            if has_data:
                return

            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                token = data.get("pixiv_refresh_token", "")
                if self.use_mariadb:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            if token:
                                cur.execute("INSERT INTO `bot_kv` (`key`, `value`) VALUES (%s, %s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`);", ("pixiv_refresh_token", token))
                            for cid, settings in data.get("chats_settings", {}).items():
                                for k, v in settings.items():
                                    cur.execute("INSERT INTO `chats_settings` (`chat_id`, `key`, `value`) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`);", (str(cid), k, json.dumps(v)))
                            for entity_id in data.get("blacklist", []):
                                cur.execute("INSERT IGNORE INTO `blacklist` (`entity_id`) VALUES (%s);", (int(entity_id),))
                            for cid, cinfo in data.get("known_chats", {}).items():
                                cur.execute("INSERT INTO `known_chats` (`chat_id`, `title`, `type`, `last_active`) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE `title`=VALUES(`title`), `type`=VALUES(`type`), `last_active`=VALUES(`last_active`);", (int(cinfo.get("id", cid)), cinfo.get("title", ""), cinfo.get("type", "group"), int(cinfo.get("last_active", time.time()))))
                else:
                    with self._get_sqlite_conn() as conn:
                        if token:
                            conn.execute("INSERT OR REPLACE INTO bot_kv (key, value) VALUES (?, ?);", ("pixiv_refresh_token", token))
                        for cid, settings in data.get("chats_settings", {}).items():
                            for k, v in settings.items():
                                conn.execute("INSERT OR REPLACE INTO chats_settings (chat_id, key, value) VALUES (?, ?, ?);", (str(cid), k, json.dumps(v)))
                        for entity_id in data.get("blacklist", []):
                            conn.execute("INSERT OR IGNORE INTO blacklist (entity_id) VALUES (?);", (int(entity_id),))
                        for cid, cinfo in data.get("known_chats", {}).items():
                            conn.execute("INSERT OR REPLACE INTO known_chats (chat_id, title, type, last_active) VALUES (?, ?, ?, ?);", (int(cinfo.get("id", cid)), cinfo.get("title", ""), cinfo.get("type", "group"), int(cinfo.get("last_active", time.time()))))
                        conn.commit()

                logger.info("✅ Успешная миграция данных из data.json в базу данных!")
            except Exception as e:
                logger.error(f"Ошибка миграции из data.json: {e}")

    def _load_all_to_cache(self):
        """Загрузка всех данных из БД в оперативную память для сверхбыстрого доступа (0 мс)."""
        with self._lock:
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT `chat_id`, `key`, `value` FROM `chats_settings`;")
                            for cid, k, v in cur.fetchall():
                                if cid not in self._chats_settings:
                                    self._chats_settings[cid] = DEFAULT_SETTINGS.copy()
                                try:
                                    self._chats_settings[cid][k] = json.loads(v)
                                except Exception:
                                    self._chats_settings[cid][k] = v

                            cur.execute("SELECT `chat_id`, `title`, `type`, `last_active` FROM `known_chats`;")
                            for cid, title, ctype, last_active in cur.fetchall():
                                self._known_chats[str(cid)] = {
                                    "id": cid,
                                    "title": title,
                                    "type": ctype,
                                    "last_active": last_active
                                }

                            cur.execute("SELECT `entity_id` FROM `blacklist`;")
                            self._blacklist = {r[0] for r in cur.fetchall()}

                            cur.execute("SELECT `value` FROM `bot_kv` WHERE `key` = 'pixiv_refresh_token';")
                            row = cur.fetchone()
                            self._pixiv_token = row[0] if row else ""
                    return
                except Exception as e:
                    logger.error(f"[Database] Ошибка загрузки кэша из MariaDB: {e}")

            # Fallback к SQLite
            with self._get_sqlite_conn() as conn:
                rows = conn.execute("SELECT chat_id, key, value FROM chats_settings;").fetchall()
                for cid, k, v in rows:
                    if cid not in self._chats_settings:
                        self._chats_settings[cid] = DEFAULT_SETTINGS.copy()
                    try:
                        self._chats_settings[cid][k] = json.loads(v)
                    except Exception:
                        self._chats_settings[cid][k] = v

                rows = conn.execute("SELECT chat_id, title, type, last_active FROM known_chats;").fetchall()
                for cid, title, ctype, last_active in rows:
                    self._known_chats[str(cid)] = {
                        "id": cid,
                        "title": title,
                        "type": ctype,
                        "last_active": last_active
                    }

                rows = conn.execute("SELECT entity_id FROM blacklist;").fetchall()
                self._blacklist = {r[0] for r in rows}

                row = conn.execute("SELECT value FROM bot_kv WHERE key = 'pixiv_refresh_token';").fetchone()
                self._pixiv_token = row[0] if row else ""

    def _save_json_backup(self):
        """Фоновое дублирование в JSON для ручного просмотра."""
        try:
            backup_data = {
                "pixiv_refresh_token": self._pixiv_token,
                "chats_settings": self._chats_settings,
                "blacklist": list(self._blacklist),
                "known_chats": self._known_chats
            }
            tmp = self.json_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            tmp.replace(self.json_path)
        except Exception as e:
            logger.debug(f"[Database] Error writing json backup: {e}")

    # Pixiv token
    def get_pixiv_token(self) -> str:
        return self._pixiv_token

    def set_pixiv_token(self, token: str):
        val = token.strip()
        self._pixiv_token = val
        with self._lock:
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO `bot_kv` (`key`, `value`) VALUES ('pixiv_refresh_token', %s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`);",
                                (val,)
                            )
                except Exception as e:
                    logger.error(f"[Database] MariaDB error in set_pixiv_token: {e}")
            else:
                with self._get_sqlite_conn() as conn:
                    conn.execute("INSERT OR REPLACE INTO bot_kv (key, value) VALUES ('pixiv_refresh_token', ?);", (val,))
                    conn.commit()
        self._save_json_backup()

    # Per-chat settings
    def get_chat_setting(self, chat_id: int, key: str, default: Any = None) -> Any:
        cid = str(chat_id)
        chat_dict = self._chats_settings.get(cid)
        if chat_dict and key in chat_dict:
            return chat_dict[key]
        if key in DEFAULT_SETTINGS:
            return DEFAULT_SETTINGS[key]
        return default

    def set_chat_setting(self, chat_id: int, key: str, value: Any):
        cid = str(chat_id)
        if cid not in self._chats_settings:
            self._chats_settings[cid] = DEFAULT_SETTINGS.copy()
        self._chats_settings[cid][key] = value

        val_json = json.dumps(value)
        with self._lock:
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO `chats_settings` (`chat_id`, `key`, `value`) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`);",
                                (cid, key, val_json)
                            )
                except Exception as e:
                    logger.error(f"[Database] MariaDB error in set_chat_setting: {e}")
            else:
                with self._get_sqlite_conn() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO chats_settings (chat_id, key, value) VALUES (?, ?, ?);",
                        (cid, key, val_json)
                    )
                    conn.commit()

        self._save_json_backup()

    def get_all_chat_settings(self, chat_id: int) -> Dict[str, Any]:
        cid = str(chat_id)
        settings = DEFAULT_SETTINGS.copy()
        custom = self._chats_settings.get(cid, {})
        settings.update(custom)
        return settings

    # Blacklist by ID
    def is_blacklisted(self, entity_id: int) -> bool:
        return entity_id in self._blacklist

    def get_blacklist(self) -> Set[int]:
        return self._blacklist.copy()

    def add_to_blacklist(self, entity_id: int) -> bool:
        if entity_id in self._blacklist:
            return False
        self._blacklist.add(entity_id)
        with self._lock:
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("INSERT IGNORE INTO `blacklist` (`entity_id`) VALUES (%s);", (entity_id,))
                except Exception as e:
                    logger.error(f"[Database] MariaDB error in add_to_blacklist: {e}")
            else:
                with self._get_sqlite_conn() as conn:
                    conn.execute("INSERT OR IGNORE INTO blacklist (entity_id) VALUES (?);", (entity_id,))
                    conn.commit()
        self._save_json_backup()
        return True

    def remove_from_blacklist(self, entity_id: int) -> bool:
        if entity_id not in self._blacklist:
            return False
        self._blacklist.discard(entity_id)
        with self._lock:
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM `blacklist` WHERE `entity_id` = %s;", (entity_id,))
                except Exception as e:
                    logger.error(f"[Database] MariaDB error in remove_from_blacklist: {e}")
            else:
                with self._get_sqlite_conn() as conn:
                    conn.execute("DELETE FROM blacklist WHERE entity_id = ?;", (entity_id,))
                    conn.commit()
        self._save_json_backup()
        return True

    # Known chats tracking
    def record_chat(self, chat_id: int, title: str, chat_type: str):
        cid = str(chat_id)
        now = int(time.time())
        info = {
            "id": chat_id,
            "title": title or f"Чат {chat_id}",
            "type": str(chat_type),
            "last_active": now
        }
        self._known_chats[cid] = info

        with self._lock:
            if self.use_mariadb:
                try:
                    with self._get_mariadb_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO `known_chats` (`chat_id`, `title`, `type`, `last_active`) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE `title`=VALUES(`title`), `type`=VALUES(`type`), `last_active`=VALUES(`last_active`);",
                                (chat_id, info["title"], info["type"], now)
                            )
                except Exception as e:
                    logger.error(f"[Database] MariaDB error in record_chat: {e}")
            else:
                with self._get_sqlite_conn() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO known_chats (chat_id, title, type, last_active) VALUES (?, ?, ?, ?);",
                        (chat_id, info["title"], info["type"], now)
                    )
                    conn.commit()
        self._save_json_backup()

    def get_known_chats(self) -> List[Dict[str, Any]]:
        chats = list(self._known_chats.values())
        chats.sort(key=lambda x: x.get("last_active", 0), reverse=True)
        return chats

db = Database()
