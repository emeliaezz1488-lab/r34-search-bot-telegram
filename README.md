# NSFW Telegram Bot

Asynchronous Telegram bot for searching and streaming media from Rule34, Danbooru, Konachan, Pixiv, and Pornhub. Built with Python 3, aiogram 3, and aiohttp.

---

## Features

- Multi-source search: Rule34, Danbooru, Konachan, Pixiv (SFW and R-18), and Pornhub.
- Intelligent media grouping: automatically groups photos and streamable MP4 videos into albums under Telegram's 50 MB payload budget.
- Individual chat settings (`/settings`): per-chat configuration for spoilers, auto-deletion timers, chat triggers, anti-spam, and default search providers.
- Dual database support: high-performance MariaDB / MySQL integration with automatic zero-configuration SQLite fallback.
- Content normalization: on-the-fly image dimension optimization and fast FFmpeg video transcoding to streamable H.264 MP4.
- Pixiv integration: automatic token keepalive loop and R-18 manga album compiler.
- Protection and moderation: rate-limiting (token bucket), per-user concurrent task limits, and admin panel with chat blacklisting.

---

## Requirements

- Linux (Ubuntu 20.04+, Debian 11+, or any standard distribution) or Windows / macOS
- Python 3.10 or higher
- FFmpeg (required for video format conversion and streaming optimization)
- MariaDB / MySQL server (optional; local SQLite is used by default)

---

## VDS Deployment Guide

### 1. System Preparation

Update package indexes and install required system utilities, Python development tools, and FFmpeg:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git ffmpeg
```

Verify that Python and FFmpeg are available:

```bash
python3 --version
ffmpeg -version
```

### 2. Clone Repository and Set Up Virtual Environment

Clone the repository to your preferred location (for example, `/opt/nsfw_bot` or your home directory):

```bash
git clone <YOUR_REPOSITORY_URL> /opt/nsfw_bot
cd /opt/nsfw_bot
```

Create an isolated virtual environment and activate it:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install Python dependencies:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Environment Configuration

Copy the example environment file and open it for editing:

```bash
cp .env.example .env
nano .env
```

Configure the following parameters:

```ini
# Required: Telegram Bot Token from @BotFather
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ

# Required: Telegram user IDs granted administrative access (comma-separated)
ADMIN_IDS=6869409295,6523714964

# Required for Pixiv: OAuth Refresh Token
PIXIV_REFRESH_TOKEN=

# Maximum search results requested per query (default: 100)
POSTS_COUNT=100

# Optional: MariaDB/MySQL credentials (leave DB_HOST empty to use SQLite)
DB_HOST=
DB_PORT=3306
DB_USER=
DB_PASSWORD=
DB_NAME=nsfw_bot
```

---

## Obtaining a Pixiv Refresh Token

Pixiv requires an OAuth PKCE refresh token for API requests. A standalone helper script is included in the repository.

1. Ensure your virtual environment is active:
   ```bash
   source venv/bin/activate
   ```

2. Run the helper script:
   ```bash
   python get_pixiv_token.py
   ```

3. The script displays an official Pixiv login URL:
   - Open the URL in any web browser.
   - Sign into your Pixiv account.
   - After authentication, the browser will redirect to a blank or callback page with `pixiv://` or `app-api.pixiv.net`.
   - Open Developer Tools (`F12`), go to the **Network** tab, locate the callback request, and copy the `code` parameter (or copy the entire callback URL).
   - Paste it into the script prompt.

4. The script exchanges the authorization code for a `refresh_token` and automatically saves it to your `.env` file.

To verify that your token is functional:
```bash
python get_pixiv_token.py --check
```

---

## Database Configuration

### Option A: Local SQLite (Zero-Config, Default)

Leave `DB_HOST` empty in your `.env` file. The bot will automatically create and manage `bot_database.db` locally.

### Option B: MariaDB / MySQL (Production)

1. Create the database and user on your database server:
   ```sql
   CREATE DATABASE nsfw_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'nsfw_user'@'localhost' IDENTIFIED BY 'your_secure_password';
   GRANT ALL PRIVILEGES ON nsfw_bot.* TO 'nsfw_user'@'localhost';
   FLUSH PRIVILEGES;
   ```

2. Import the database schema:
   ```bash
   mysql -u nsfw_user -p nsfw_bot < schema.sql
   ```

3. Fill in `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` in your `.env` file.

---

## Production Systemd Service

To ensure the bot runs 24/7 in the background and restarts automatically on system reboots or unexpected crashes, create a systemd service.

1. Create a service file:
   ```bash
   sudo nano /etc/systemd/system/nsfwbot.service
   ```

2. Paste the following configuration (adjust paths and user as necessary):
   ```ini
   [Unit]
   Description=NSFW Telegram Searcher Bot
   After=network.target

   [Service]
   Type=simple
   User=root
   WorkingDirectory=/opt/nsfw_bot
   ExecStart=/opt/nsfw_bot/venv/bin/python bot.py
   Restart=always
   RestartSec=5
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   ```

3. Reload systemd and enable the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable nsfwbot.service
   sudo systemctl start nsfwbot.service
   ```

4. Manage the service:
   - Check status: `sudo systemctl status nsfwbot.service`
   - View live logs: `sudo journalctl -u nsfwbot.service -f`
   - Restart: `sudo systemctl restart nsfwbot.service`
   - Stop: `sudo systemctl stop nsfwbot.service`

---

## Commands Reference

| Command | Arguments | Description |
|---|---|---|
| `/r34` | `[tags] [count]` | Search images and videos on Rule34 |
| `/danbooru` | `[tags] [count]` | Search illustrations on Danbooru |
| `/konachan` | `[tags] [count]` | Search wallpapers and art on Konachan |
| `/ph` | `[query] [count]` | Search videos and metadata on Pornhub |
| `/pixiv` | `[tags] [count]` | Search safe (SFW) illustrations on Pixiv |
| `/pixivnsfw` | `[tags] [count]` | Search R-18 illustrations on Pixiv |
| `/pixivmanga` | `[tags]` | Download and assemble R-18 manga albums from Pixiv |
| `/settings` | None | Open interactive settings panel for the current chat |
| `/admin` | None | Open bot administration panel (admins only) |
| `/help` | None | Display commands and trigger overview |

### Chat Triggers (without prefix)

The bot listens for direct keywords in enabled chats:

- `futa [count]` or `фута [count]` - Search futanari art
- `femboy [count]` or `фембой [count]` - Search femboy art
- `futa + femboy [count]` or `фута+фембой [count]` - Search video pairing
- `порно [count]` - Random video search
- `r34 [tags] [count]` - Direct Rule34 query
- `konachan [tags] [count]` - Direct Konachan query
- `ph [query] [count]` - Direct Pornhub query
- `pixiv [tags] [count]` - Direct Pixiv SFW query
- `pixivnsfw [tags] [count]` - Direct Pixiv R-18 query
- `pixivmanga [tags]` - Direct Pixiv manga query

---

## Security and Privacy Notice

Never commit your `.env` file, database files (`*.db`), or private chat dumps to a public GitHub repository. Ensure `.gitignore` remains intact before pushing any commits.
