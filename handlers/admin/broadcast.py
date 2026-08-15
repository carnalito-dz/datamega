"""Panel admin — Broadcast : envoyer un message à tous les clients."""
from __future__ import annotations

import asyncio

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select

from db.models import User
from db.session import get_session
from services.journal import log_action
from utils.filters import IsAdmin
from utils.states import BroadcastFlow

router = Router(name="admin_broadcast")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BroadcastFlow.writing_message)
    await callback.message.answer(
        "📣 <b>Broadcast</b>\n\n"
        "Écrivez le message à envoyer à TOUS les clients actifs.\n"
        "HTML supporté. /annuler pour abandonner."
    )
    await callback.answer()


@router.message(BroadcastFlow.writing_message, F.text == "/annuler")
async def cancel_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Broadcast annulé.")


@router.message(BroadcastFlow.writing_message)
async def confirm_broadcast(message: Message, state: FSMContext) -> None:
    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastFlow.confirming)

    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.is_banned.is_(False))
        )
        count = len(list(result.scalars().all()))

    await message.answer(
        f"⚠️ Vous allez envoyer ce message à <b>{count} clients</b>.\n\n"
        f"<i>Aperçu :</i>\n{message.text[:200]}\n\n"
        f"Confirmez-vous ?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Confirmer et envoyer", callback_data="broadcast:confirm")],
            [InlineKeyboardButton(text="❌ Annuler", callback_data="broadcast:cancel")],
        ]),
    )


@router.callback_query(BroadcastFlow.confirming, F.data == "broadcast:cancel")
async def cancel_broadcast_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Broadcast annulé.")
    await callback.answer()


@router.callback_query(BroadcastFlow.confirming, F.data == "broadcast:confirm")
async def execute_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()

    await callback.message.edit_text("⏳ Envoi en cours…")

    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.is_banned.is_(False))
        )
        users = list(result.scalars().all())
        await log_action(
            session, callback.from_user.id, "broadcast",
            f"{len(users)} destinataires"
        )

    sent = 0
    failed = 0
    for user in users:
        try:
            await callback.bot.send_message(user.telegram_id, text)
            sent += 1
        except Exception:
            failed += 1
        # Pause pour éviter les rate limits Telegram (30 msg/sec max)
        if sent % 25 == 0:
            await asyncio.sleep(1)

    await callback.message.edit_text(
        f"✅ Broadcast terminé.\n"
        f"Envoyé : {sent} | Échec : {failed}"
    )
    await callback.answer()
