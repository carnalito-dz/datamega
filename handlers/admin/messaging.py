"""
Panel admin — Messagerie support bidirectionnelle.
Permet aux admins de voir les conversations et répondre aux clients.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select

from db.models import User
from db.session import get_session
from services import support_chat
from services.journal import log_action
from utils.filters import IsAdmin
from utils.formatting import fmt_datetime
from utils.states import AdminReplyFlow

router = Router(name="admin_messaging")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _back_kb(labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("admin_back_home", "⬅️ Menu admin"),
            callback_data="admin:home",
        )]
    ])


@router.callback_query(F.data == "admin:messaging")
async def show_threads(callback: CallbackQuery, labels: dict) -> None:
    async with get_session() as session:
        threads = await support_chat.get_all_threads_preview(session)

    if not threads:
        await callback.message.edit_text(
            "💬 <b>Messagerie support</b>\n\nAucun message pour le moment.",
            reply_markup=_back_kb(labels),
        )
        await callback.answer()
        return

    rows = []
    for t in threads[:15]:
        user = t["user"]
        unread = t["unread"]
        badge = f"🔴{unread} " if unread else ""
        name = f"@{user.username}" if user.username else f"#{user.telegram_id}"
        rows.append([InlineKeyboardButton(
            text=f"{badge}{name} — {t['last_text'][:30]}",
            callback_data=f"admin:msg:thread:{user.id}",
        )])
    rows.append([InlineKeyboardButton(
        text=labels.get("admin_back_home", "⬅️ Menu admin"),
        callback_data="admin:home",
    )])

    await callback.message.edit_text(
        f"💬 <b>Messagerie support</b>\n{len(threads)} conversation(s)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:msg:thread:"))
async def show_thread(callback: CallbackQuery, state: FSMContext, labels: dict) -> None:
    user_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Utilisateur introuvable.", show_alert=True)
            return
        messages = await support_chat.get_conversation(session, user_id, limit=15)
        await support_chat.mark_thread_read(session, user_id)

    lines = [
        f"💬 <b>Conversation avec @{user.username or user.telegram_id}</b>\n"
    ]
    for msg in messages:
        direction = "👤 Client" if msg.direction.value == "client_to_admin" else "🛠 Support"
        lines.append(
            f"<b>{direction}</b> — {fmt_datetime(msg.created_at)}\n{msg.text}\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✍️ Répondre",
            callback_data=f"admin:msg:reply:{user_id}",
        )],
        [InlineKeyboardButton(
            text="⬅️ Messagerie",
            callback_data="admin:messaging",
        )],
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:msg:reply:"))
async def start_reply(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[3])
    await state.set_state(AdminReplyFlow.writing_reply)
    await state.update_data(reply_to_user_id=user_id)
    await callback.message.answer(
        "✍️ Écrivez votre réponse (/annuler pour abandonner) :"
    )
    await callback.answer()


@router.message(AdminReplyFlow.writing_reply, F.text == "/annuler")
async def cancel_reply(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Réponse annulée.")


@router.message(AdminReplyFlow.writing_reply)
async def send_reply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    user_id = data.get("reply_to_user_id")
    await state.clear()

    async with get_session() as session:
        user = await session.get(User, user_id)
        if not user:
            await message.answer("Utilisateur introuvable.")
            return
        await support_chat.send_from_admin(
            session, user_id,
            message.from_user.id,
            message.text,
            message.bot,
        )
        await log_action(
            session, message.from_user.id, "support_reply",
            f"user={user.telegram_id}",
        )

    await message.answer(
        f"✅ Réponse envoyée à @{user.username or user.telegram_id}."
    )
