import logging
from typing import Union, Dict, Any, List, Tuple
from aiogram import types
from aiogram.filters import BaseFilter
import config

logger = logging.getLogger(__name__)

PHOTO_KEYWORDS = {"jpg", "jpeg", "png", "photo", "фото", "пикча", "картинка", "картинки", "арт", "static", "image"}
VIDEO_KEYWORDS = {"video", "видео", "mp4", "webm", "mov"}
GIF_KEYWORDS = {"gif", "гиф", "гифка", "animated", "анимация"}

def smart_parse_tags_and_count(args: str, chat_id: int = 0, user_id: int = 0) -> Tuple[str, int, str]:
    """
    Умный разбор тегов, количества и медиа-фильтра:
    - Отдельное число из чистых цифр (например, '5', '3', '10') считается количеством постов.
    - Обычные пользователи ограничены максимум 10 постами.
    - Администраторы не имеют ограничений.
    - Ключевые слова типа медиа ('jpg', 'фото', 'видео', 'gif') распознаются как фильтр и не ломают поиск на Booru.
    - Слова, содержащие буквы (например, '1girl', '2boys', '3d', 'furry', 'solo'), всегда считаются ТЕГАМИ!
    Возвращает: (tags: str, count: int, media_filter: str)
    """
    default_count = config.get_send_count(chat_id)
    is_adm = config.is_admin(user_id) if user_id else False

    if not is_adm:
        default_count = min(default_count, 10)

    chat_media_filter = config.get_media_filter(chat_id)
    detected_filter = None

    if not args:
        return "", default_count, chat_media_filter

    tokens = args.strip().split()
    tag_tokens = []
    found_count = None

    for token in tokens:
        token_lower = token.lower()
        # Числом считается ТОЛЬКО отдельное слово, состоящее строго из одних цифр
        if token.isdigit() and found_count is None:
            val = int(token)
            if val > 0:
                found_count = val if is_adm else min(val, 10)
                continue

        # Проверка на фильтр типа медиа (jpg / фото / видео / gif)
        if token_lower in PHOTO_KEYWORDS and detected_filter is None:
            detected_filter = "photo"
            continue
        elif token_lower in VIDEO_KEYWORDS and detected_filter is None:
            detected_filter = "video"
            continue
        elif token_lower in GIF_KEYWORDS and detected_filter is None:
            detected_filter = "gif"
            continue

        tag_tokens.append(token)

    tags = " ".join(tag_tokens).strip()
    count = found_count if found_count is not None else default_count
    if not is_adm:
        count = min(count, 10)

    final_filter = detected_filter or chat_media_filter
    return tags, count, final_filter

class FlexibleCommand(BaseFilter):
    """
    Гибкий фильтр команд.
    Распознает:
    - /r34 anime 2
    - /r34@my_bot anime 2
    - /r34@other_bot anime 2
    """
    def __init__(self, *names: str):
        self.names = [n.lower().lstrip("/") for n in names]

    async def __call__(self, message: types.Message) -> Union[bool, Dict[str, Any]]:
        text = (message.text or message.caption or "").strip()
        if not text.startswith("/"):
            return False

        parts = text.split(maxsplit=1)
        raw_cmd = parts[0][1:]
        args = parts[1].strip() if len(parts) > 1 else ""

        cmd_name = raw_cmd.split("@")[0].lower()

        if cmd_name in self.names:
            return {"cmd_name": cmd_name, "cmd_args": args}
        return False
