import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db

logger = logging.getLogger(__name__)

router = Router(name="settings")

DELAY_OPTIONS = [15, 30, 60, 120, 300]
COUNT_OPTIONS = [1, 2, 3, 5, 10]
MANGA_PAGES_OPTIONS = [20, 40, 60, 80, 100]
SOURCE_OPTIONS = ["rule34", "danbooru", "pixiv", "konachan"]
MEDIA_TYPE_OPTIONS = ["all", "photo", "video"]
MEDIA_TYPE_LABELS = {
    "all": "Все (фото и видео)",
    "photo": "Только фото (JPG)",
    "video": "Только видео"
}
MEDIA_TYPE_BUTTON_LABELS = {
    "all": "Все",
    "photo": "Фото (JPG)",
    "video": "Видео"
}

def get_settings_markup(chat_id: int) -> InlineKeyboardMarkup:
    triggers = db.get_chat_setting(chat_id, "triggers_enabled", True)
    source = db.get_chat_setting(chat_id, "default_source", "rule34")
    spoiler = db.get_chat_setting(chat_id, "spoiler_media", True)
    autodel = db.get_chat_setting(chat_id, "auto_delete", True)
    delay = db.get_chat_setting(chat_id, "auto_delete_delay", 30)
    antispam = db.get_chat_setting(chat_id, "spam_protection", True)
    antiai = db.get_chat_setting(chat_id, "antiai", True)
    send_count = db.get_chat_setting(chat_id, "send_count", 1)
    manga_pages = db.get_chat_setting(chat_id, "pixiv_manga_max_pages", 40)
    media_filter = db.get_chat_setting(chat_id, "media_filter", "all")
    btn_media = MEDIA_TYPE_BUTTON_LABELS.get(media_filter, "Все")

    kb = [
        [
            InlineKeyboardButton(
                text=f"⚡ Триггеры: {'✅ Вкл' if triggers else '❌ Выкл'}",
                callback_data="set:triggers"
            ),
            InlineKeyboardButton(
                text=f"🌐 Источник: {source.upper()}",
                callback_data="set:source"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"👁 Спойлеры: {'✅ Вкл' if spoiler else '❌ Выкл'}",
                callback_data="set:spoiler"
            ),
            InlineKeyboardButton(
                text=f"🛡 Анти-спам: {'✅ Вкл' if antispam else '❌ Выкл'}",
                callback_data="set:antispam"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⏳ Автоудаление: {'✅ Вкл' if autodel else '❌ Выкл'}",
                callback_data="set:autodel"
            ),
            InlineKeyboardButton(
                text=f"⏱ Задержка: {delay} сек",
                callback_data="set:delay"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🤖 Фильтр AI: {'✅ Вкл' if antiai else '❌ Выкл'}",
                callback_data="set:antiai"
            ),
            InlineKeyboardButton(
                text=f"📦 Постов за раз: {send_count} шт",
                callback_data="set:sendcount"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📖 Манга макс: {manga_pages} стр",
                callback_data="set:manga"
            ),
            InlineKeyboardButton(
                text=f"🖼 Медиа: {btn_media}",
                callback_data="set:mediatype"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Закрыть меню",
                callback_data="set:close"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_settings_text(chat_id: int) -> str:
    triggers = db.get_chat_setting(chat_id, "triggers_enabled", True)
    source = db.get_chat_setting(chat_id, "default_source", "rule34")
    spoiler = db.get_chat_setting(chat_id, "spoiler_media", True)
    autodel = db.get_chat_setting(chat_id, "auto_delete", True)
    delay = db.get_chat_setting(chat_id, "auto_delete_delay", 30)
    antispam = db.get_chat_setting(chat_id, "spam_protection", True)
    antiai = db.get_chat_setting(chat_id, "antiai", True)
    send_count = db.get_chat_setting(chat_id, "send_count", 1)
    manga_pages = db.get_chat_setting(chat_id, "pixiv_manga_max_pages", 40)
    media_filter = db.get_chat_setting(chat_id, "media_filter", "all")
    media_desc = MEDIA_TYPE_LABELS.get(media_filter, "Все")

    return (
        "⚙️ <b>Панель настроек чата</b>\n\n"
        "<i>Настройки сохраняются отдельно для этой группы/чата.</i>\n\n"
        f"• <b>Триггеры в чате:</b> {'✅ Включены' if triggers else '❌ Отключены'}\n"
        f"• <b>Источник по умолчанию:</b> <code>{source.upper()}</code>\n"
        f"• <b>Спойлеры на медиа:</b> {'✅ Скрывать' if spoiler else '❌ Открыто'}\n"
        f"• <b>Анти-спам защита:</b> {'✅ Активна' if antispam else '❌ Выключена'}\n"
        f"• <b>Автоудаление постов:</b> {'✅ Включено' if autodel else '❌ Выключено'} (таймаут: {delay}с)\n"
        f"• <b>Фильтр AI-артов:</b> {'✅ Отсеивать AI' if antiai else '❌ Разрешать'}\n"
        f"• <b>Постов за команду:</b> <code>{send_count}</code> шт.\n"
        f"• <b>Макс. страниц манги:</b> <code>{manga_pages}</code> стр.\n"
        f"• <b>Фильтр формата медиа:</b> <code>{media_desc}</code>\n"
    )

from utils.filters import FlexibleCommand

@router.message(FlexibleCommand("settings"))
async def cmd_settings(message: types.Message, cmd_name: str = "", cmd_args: str = ""):
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    logger.info(f"▶️ [CMD:/settings] User: {user_id} | Chat: {chat_id}")

    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        logger.warning(f"⛔ Блеклист: отказ /settings для user {user_id} в {chat_id}")
        return

    db.record_chat(
        chat_id,
        message.chat.title or message.chat.full_name or "Личка",
        str(message.chat.type)
    )

    await message.reply(
        get_settings_text(chat_id),
        reply_markup=get_settings_markup(chat_id),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("set:"))
async def process_setting_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    if db.is_blacklisted(user_id) or db.is_blacklisted(chat_id):
        await callback.answer("⛔ Вы в черном списке бота.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]
    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer("Настройки закрыты")
        return

    if action == "triggers":
        cur = db.get_chat_setting(chat_id, "triggers_enabled", True)
        db.set_chat_setting(chat_id, "triggers_enabled", not cur)
        await callback.answer(f"Триггеры: {'Включены' if not cur else 'Выключены'}")

    elif action == "source":
        cur = db.get_chat_setting(chat_id, "default_source", "rule34").lower()
        idx = SOURCE_OPTIONS.index(cur) if cur in SOURCE_OPTIONS else 0
        new_source = SOURCE_OPTIONS[(idx + 1) % len(SOURCE_OPTIONS)]
        db.set_chat_setting(chat_id, "default_source", new_source)
        await callback.answer(f"Источник: {new_source.upper()}")

    elif action == "spoiler":
        cur = db.get_chat_setting(chat_id, "spoiler_media", True)
        db.set_chat_setting(chat_id, "spoiler_media", not cur)
        await callback.answer(f"Спойлеры: {'Включены' if not cur else 'Выключены'}")

    elif action == "antispam":
        cur = db.get_chat_setting(chat_id, "spam_protection", True)
        db.set_chat_setting(chat_id, "spam_protection", not cur)
        await callback.answer(f"Анти-спам: {'Включен' if not cur else 'Выключен'}")

    elif action == "autodel":
        cur = db.get_chat_setting(chat_id, "auto_delete", True)
        db.set_chat_setting(chat_id, "auto_delete", not cur)
        await callback.answer(f"Автоудаление: {'Включено' if not cur else 'Выключено'}")

    elif action == "delay":
        cur = db.get_chat_setting(chat_id, "auto_delete_delay", 30)
        idx = DELAY_OPTIONS.index(cur) if cur in DELAY_OPTIONS else 1
        new_delay = DELAY_OPTIONS[(idx + 1) % len(DELAY_OPTIONS)]
        db.set_chat_setting(chat_id, "auto_delete_delay", new_delay)
        await callback.answer(f"Задержка: {new_delay} сек")

    elif action == "antiai":
        cur = db.get_chat_setting(chat_id, "antiai", True)
        db.set_chat_setting(chat_id, "antiai", not cur)
        await callback.answer(f"Фильтр AI: {'Включен' if not cur else 'Выключен'}")

    elif action == "sendcount":
        cur = db.get_chat_setting(chat_id, "send_count", 1)
        idx = COUNT_OPTIONS.index(cur) if cur in COUNT_OPTIONS else 0
        new_count = COUNT_OPTIONS[(idx + 1) % len(COUNT_OPTIONS)]
        db.set_chat_setting(chat_id, "send_count", new_count)
        await callback.answer(f"Постов за раз: {new_count}")

    elif action == "manga":
        cur = db.get_chat_setting(chat_id, "pixiv_manga_max_pages", 40)
        idx = MANGA_PAGES_OPTIONS.index(cur) if cur in MANGA_PAGES_OPTIONS else 1
        new_pages = MANGA_PAGES_OPTIONS[(idx + 1) % len(MANGA_PAGES_OPTIONS)]
        db.set_chat_setting(chat_id, "pixiv_manga_max_pages", new_pages)
        await callback.answer(f"Макс. страниц манги: {new_pages}")

    elif action == "mediatype":
        cur = db.get_chat_setting(chat_id, "media_filter", "all").lower()
        idx = MEDIA_TYPE_OPTIONS.index(cur) if cur in MEDIA_TYPE_OPTIONS else 0
        new_type = MEDIA_TYPE_OPTIONS[(idx + 1) % len(MEDIA_TYPE_OPTIONS)]
        db.set_chat_setting(chat_id, "media_filter", new_type)
        await callback.answer(f"Тип медиа: {MEDIA_TYPE_BUTTON_LABELS.get(new_type, new_type)}")

    try:
        await callback.message.edit_text(
            get_settings_text(chat_id),
            reply_markup=get_settings_markup(chat_id),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"[Settings] edit_text exception: {e}")
