import logging
import math
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import config
from database import db
from utils.task_tracker import task_tracker

logger = logging.getLogger(__name__)

router = Router(name="admin")

PAGE_SIZE = 5

def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID

def get_admin_main_markup() -> InlineKeyboardMarkup:
    bl_count = len(db.get_blacklist())
    chats_count = len(db.get_known_chats())

    kb = [
        [
            InlineKeyboardButton(
                text=f"📋 Список чатов ({chats_count}) / Отмена запросов",
                callback_data="adm:chats:0"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🚫 Блеклист по ID ({bl_count})",
                callback_data="adm:blacklist"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Закрыть админку",
                callback_data="adm:close"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_main_text() -> str:
    bl = db.get_blacklist()
    chats = db.get_known_chats()
    return (
        "🛡 <b>Панель администратора</b>\n\n"
        f"• <b>Администратор ID:</b> <code>{config.ADMIN_ID}</code>\n"
        f"• <b>Известных чатов бота:</b> <code>{len(chats)}</code>\n"
        f"• <b>В блеклисте:</b> <code>{len(bl)}</code> ID\n\n"
        "Выбери нужный раздел ниже:"
    )

@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id if message.from_user else 0
    if not is_admin(user_id):
        await message.reply("⛔ <b>Доступ запрещен!</b> Эта команда доступна только администратору.", parse_mode="HTML")
        return

    raw_args = message.text.split(maxsplit=2)[1:] if len(message.text.split(maxsplit=2)) > 1 else []
    if raw_args:
        subcmd = raw_args[0].lower()
        if subcmd == "ban" and len(raw_args) > 1:
            try:
                target_id = int(raw_args[1])
                if db.add_to_blacklist(target_id):
                    await message.reply(f"✅ ID <code>{target_id}</code> добавлен в блеклист.", parse_mode="HTML")
                else:
                    await message.reply(f"⚠️ ID <code>{target_id}</code> уже в блеклисте.", parse_mode="HTML")
            except ValueError:
                await message.reply("❌ ID должен быть числом!", parse_mode="HTML")
            return

        if subcmd == "unban" and len(raw_args) > 1:
            try:
                target_id = int(raw_args[1])
                if db.remove_from_blacklist(target_id):
                    await message.reply(f"✅ ID <code>{target_id}</code> удален из блеклиста.", parse_mode="HTML")
                else:
                    await message.reply(f"⚠️ ID <code>{target_id}</code> не найден в блеклисте.", parse_mode="HTML")
            except ValueError:
                await message.reply("❌ ID должен быть числом!", parse_mode="HTML")
            return

    await message.reply(
        get_admin_main_text(),
        reply_markup=get_admin_main_markup(),
        parse_mode="HTML"
    )

# Обработка колбэков админки
@router.callback_query(F.data.startswith("adm:"))
async def process_admin_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer("⛔ Доступ запрещен!", show_alert=True)
        return

    parts = callback.data.split(":")
    action = parts[1]

    # Закрытие меню
    if action == "close":
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        return

    # Главное меню админки
    if action == "main":
        await callback.message.edit_text(
            get_admin_main_text(),
            reply_markup=get_admin_main_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Список чатов с пагинацией (максимум по 5 чатов)
    if action == "chats":
        page = int(parts[2]) if len(parts) > 2 else 0
        chats = db.get_known_chats()
        total_chats = len(chats)
        total_pages = max(1, math.ceil(total_chats / PAGE_SIZE))
        page = max(0, min(page, total_pages - 1))

        start_idx = page * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        page_chats = chats[start_idx:end_idx]

        kb = []
        for chat in page_chats:
            cid = chat["id"]
            title = chat.get("title", f"Чат {cid}")
            active_tasks = task_tracker.get_active_tasks_count(cid)
            status_badge = f" [🔥 Запросов: {active_tasks}]" if active_tasks > 0 else ""
            btn_text = f"💬 {title[:25]}{status_badge}"
            kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"adm:viewchat:{cid}:{page}")])

        # Кнопки пагинации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm:chats:{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"adm:chats:{page + 1}"))

        if nav_buttons:
            kb.append(nav_buttons)

        kb.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="adm:main")])

        text = (
            "📋 <b>Список чатов и каналов бота</b>\n\n"
            f"Всего чатов: <b>{total_chats}</b> (по 5 на страницу).\n"
            "Выбери нужный чат, чтобы отменить его запросы или заблокировать:"
        )

        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        await callback.answer()
        return

    # Просмотр конкретного чата
    if action == "viewchat":
        chat_id = int(parts[2])
        from_page = parts[3] if len(parts) > 3 else "0"
        chats_dict = {c["id"]: c for c in db.get_known_chats()}
        chat_info = chats_dict.get(chat_id, {"id": chat_id, "title": f"Чат {chat_id}", "type": "unknown"})

        active_tasks = task_tracker.get_active_tasks_count(chat_id)
        is_bl = db.is_blacklisted(chat_id)

        kb = [
            [
                InlineKeyboardButton(
                    text=f"🛑 Отменить активные запросы ({active_tasks})",
                    callback_data=f"adm:cancel:{chat_id}:{from_page}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🟢 Разблокировать чат" if is_bl else "🚫 Добавить чат в блеклист",
                    callback_data=f"adm:togglebl:{chat_id}:{from_page}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Вернуться к списку чатов",
                    callback_data=f"adm:chats:{from_page}"
                )
            ]
        ]

        text = (
            f"💬 <b>Управление чатом:</b> <code>{chat_info.get('title')}</code>\n\n"
            f"• <b>ID:</b> <code>{chat_id}</code>\n"
            f"• <b>Тип:</b> <code>{chat_info.get('type')}</code>\n"
            f"• <b>Активных запросов сейчас:</b> <code>{active_tasks}</code>\n"
            f"• <b>В блеклисте:</b> {'Да ⛔' if is_bl else 'Нет ✅'}\n"
        )

        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        await callback.answer()
        return

    # Отмена запросов в конкретном чате
    if action == "cancel":
        chat_id = int(parts[2])
        from_page = parts[3] if len(parts) > 3 else "0"
        cancelled = task_tracker.cancel_chat_tasks(chat_id)

        try:
            await callback.bot.send_message(
                chat_id=chat_id,
                text="⚠️ <b>Администратор отменил текущие запросы поиска/скачивания в этом чате.</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await callback.answer(f"Отменено запросов: {cancelled}", show_alert=True)
        # Перезагружаем карточку чата
        callback.data = f"adm:viewchat:{chat_id}:{from_page}"
        await process_admin_callback(callback)
        return

    # Переключение блеклиста для чата
    if action == "togglebl":
        chat_id = int(parts[2])
        from_page = parts[3] if len(parts) > 3 else "0"
        if db.is_blacklisted(chat_id):
            db.remove_from_blacklist(chat_id)
            await callback.answer("Чат разблокирован!")
        else:
            db.add_to_blacklist(chat_id)
            # При блокировке чата также отменяем все его запросы
            task_tracker.cancel_chat_tasks(chat_id)
            await callback.answer("Чат добавлен в блеклист!", show_alert=True)

        callback.data = f"adm:viewchat:{chat_id}:{from_page}"
        await process_admin_callback(callback)
        return

    # Меню блеклиста
    if action == "blacklist":
        bl = sorted(db.get_blacklist())
        text = "🚫 <b>Черный список (Блеклист)</b>\n\n"
        if not bl:
            text += "<i>Блеклист пуст.</i>\n\n"
        else:
            text += f"Всего в списке: <b>{len(bl)}</b> ID\n\n"
            for b_id in bl[:20]:
                text += f"• <code>{b_id}</code>\n"
            if len(bl) > 20:
                text += f"<i>...и еще {len(bl) - 20} ID</i>\n"

        text += (
            "\n<b>Быстрые команды:</b>\n"
            "• <code>/admin ban [ID]</code> — заблокировать ID (юзера или чат)\n"
            "• <code>/admin unban [ID]</code> — разблокировать ID"
        )

        kb = [[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="adm:main")]]
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
        await callback.answer()
        return

@router.callback_query(F.data == "noop")
async def process_noop(callback: types.CallbackQuery):
    await callback.answer()
