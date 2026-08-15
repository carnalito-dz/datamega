"""Handler support client — messagerie bidirectionnelle."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from db.session import get_session
from services import support_chat
from services.messages import get_message
from services.settings import get_support_username
from services.wallet import get_or_create_user
from utils.filters import MatchesLabel
from utils.states import SupportFlow

router = Router(name="user_support")


@router.message(MatchesLabel("menu_support"))
async def show_support(message: Message, labels: dict) -> None:
    async with get_session() as session:
        support_username = await get_support_username(session)
        text = await get_message(session, "support_text")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("support_contact", "✉️ Contacter le support"),
            url=f"https://t.me/{support_username.lstrip('@')}",
        )],
        [InlineKeyboardButton(
            text="💬 Envoyer un message",
            callback_data="support:write",
        )],
        [InlineKeyboardButton(
            text="📜 Voir mes messages",
            callback_data="support:history",
        )],
    ])
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "support:write")
async def start_support_message(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SupportFlow.writing_message)
    await callback.message.answer(
        "✍️ Écrivez votre message au support (/annuler pour abandonner) :"
    )
    await callback.answer()


@router.message(SupportFlow.writing_message, F.text == "/annuler")
async def cancel_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Message annulé.")


@router.message(SupportFlow.writing_message)
async def send_support_message(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with get_session() as session:
        user = await get_or_create_user(
            session, message.from_user.id,
            message.from_user.username, message.from_user.full_name,
        )
        await support_chat.send_from_client(session, user.id, message.text, message.bot)

    await message.answer(
        "✅ Votre message a été envoyé au support.\n"
        "Nous vous répondrons ici dès que possible."
    )


@router.callback_query(F.data == "support:history")
async def show_support_history(callback: CallbackQuery) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.username, callback.from_user.full_name,
        )
        messages = await support_chat.get_conversation(session, user.id, limit=10)

    if not messages:
        await callback.answer("Aucun message dans votre fil de support.", show_alert=True)
        return

    from utils.formatting import fmt_datetime
    lines = ["📜 <b>Vos échanges avec le support</b>\n"]
    for msg in messages:
        direction = "Vous" if msg.direction.value == "client_to_admin" else "Support"
        lines.append(f"<b>{direction}</b> — {fmt_datetime(msg.created_at)}\n{msg.text}\n")

    await callback.message.answer("\n".join(lines))
    await callback.answer()
