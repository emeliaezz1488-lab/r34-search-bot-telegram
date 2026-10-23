import sqlite3
import json
from pathlib import Path

db_path = Path("bot_database.db")
if not db_path.exists():
    print("Database file not found!")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

tables = ["chats_settings", "known_chats", "blacklist", "bot_kv"]

sql_lines = [
    "-- MariaDB / MySQL Database Dump for NSFW Telegram Bot",
    "-- Generated automatically",
    "",
    "/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;",
    "/*!40101 SET NAMES utf8mb4 */;",
    "/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;",
    "/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;",
    "",
    "-- Table structure for chats_settings",
    "CREATE TABLE IF NOT EXISTS `chats_settings` (",
    "  `chat_id` VARCHAR(64) NOT NULL,",
    "  `key` VARCHAR(64) NOT NULL,",
    "  `value` TEXT NOT NULL,",
    "  PRIMARY KEY (`chat_id`, `key`)",
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
    "",
    "-- Table structure for known_chats",
    "CREATE TABLE IF NOT EXISTS `known_chats` (",
    "  `chat_id` BIGINT NOT NULL,",
    "  `title` VARCHAR(255) NOT NULL DEFAULT '',",
    "  `type` VARCHAR(32) NOT NULL DEFAULT 'group',",
    "  `last_active` BIGINT NOT NULL DEFAULT 0,",
    "  PRIMARY KEY (`chat_id`)",
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
    "",
    "-- Table structure for blacklist",
    "CREATE TABLE IF NOT EXISTS `blacklist` (",
    "  `entity_id` BIGINT NOT NULL,",
    "  PRIMARY KEY (`entity_id`)",
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
    "",
    "-- Table structure for bot_kv",
    "CREATE TABLE IF NOT EXISTS `bot_kv` (",
    "  `key` VARCHAR(64) NOT NULL,",
    "  `value` TEXT NOT NULL,",
    "  PRIMARY KEY (`key`)",
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;",
    "",
]

for table in tables:
    try:
        cursor.execute(f"SELECT * FROM {table};")
        rows = cursor.fetchall()
        if not rows:
            continue
        
        sql_lines.append(f"-- Dumping data for table `{table}`")
        cursor.execute(f"PRAGMA table_info({table});")
        cols = [col[1] for col in cursor.fetchall()]
        cols_str = ", ".join([f"`{c}`" for c in cols])
        
        for row in rows:
            vals = []
            for v in row:
                if v is None:
                    vals.append("NULL")
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
                else:
                    v_str = str(v).replace("\\", "\\\\").replace("'", "\\'")
                    vals.append(f"'{v_str}'")
            vals_str = ", ".join(vals)
            sql_lines.append(f"INSERT INTO `{table}` ({cols_str}) VALUES ({vals_str}) ON DUPLICATE KEY UPDATE {', '.join([f'`{c}`=VALUES(`{c}`)' for c in cols])};")
        sql_lines.append("")
    except Exception as e:
        print(f"Error dumping table {table}: {e}")

output_sql = "\n".join(sql_lines)
with open("dump.sql", "w", encoding="utf-8") as f:
    f.write(output_sql)

print("Dump successfully generated: dump.sql")
print("Total rows dumped:")
for table in tables:
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table};")
        cnt = cursor.fetchone()[0]
        print(f"  {table}: {cnt}")
    except Exception:
        pass
