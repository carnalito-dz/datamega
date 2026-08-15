"""Compte client — solde, points, parrainage, historique."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from db.models import Order, OrderStatus, Product
from db.session import get_session
from services import loyalty, referral
from services.wallet import get_or_create_user, get_wallet
from utils.filters import MatchesLabel
from utils.formatting import fmt_datetime, fmt_money

router = Router(name="user_account")


@router.message(MatchesLabel("menu_account"))
async def show_account(message: Message) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, message.from_user.id,
            message.from_user.username, message.from_user.full_name,
        )
        w = await get_wallet(session, user.id)
        result = await session.execute(
            select(Order).where(
                Order.user_id == user.id,
                Order.status == OrderStatus.DELIVERED,
            )
        )
        nb_achats = len(list(result.scalars().all()))
        points, points_value = await loyalty.get_balance(session, user.id)
        ref_code = await referral.get_or_create_code(session, user.id)
        ref_stats = await referral.get_referral_stats(session, user.id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Échanger mes points", callback_data="account:redeem_points")],
        [InlineKeyboardButton(text="🔗 Mon lien de parrainage", callback_data="account:referral_link")],
    ])

    import config
    bot_info_key = "bot_username"
    try:
        me = await message.bot.get_me()
        bot_username = me.username
    except Exception:
        bot_username = "datamega_bot"

    await message.answer(
        f"👤 <b>Mon compte</b>\n\n"
        f"ID Telegram : <code>{message.from_user.id}</code>\n"
        f"Nom d'utilisateur : @{message.from_user.username or '—'}\n"
        f"Solde : <b>{fmt_money(w.balance_cents)}</b>\n"
        f"⭐ Points fidélité : <b>{points}</b> (≈ {fmt_money(points_value)})\n"
        f"Achats effectués : {nb_achats}\n"
        f"Filleuls parrainés : {ref_stats['count']}\n"
        f"Membre depuis : {fmt_datetime(user.created_at)}",
        reply_markup=kb,
    )


@router.callback_query(F.data == "account:redeem_points")
async def redeem_points_menu(callback: CallbackQuery) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.username, callback.from_user.full_name,
        )
        points, points_value = await loyalty.get_balance(session, user.id)
        enabled = await loyalty.is_enabled(session)

    if not enabled:
        await callback.answer("Le programme fidélité est désactivé.", show_alert=True)
        return

    if points <= 0:
        await callback.answer("Vous n'avez pas de points à échanger.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Échanger TOUS mes points ({points} → {fmt_money(points_value)})",
            callback_data=f"account:redeem:{points}",
        )],
        [InlineKeyboardButton(text="Annuler", callback_data="account:cancel")],
    ])
    await callback.message.answer(
        f"⭐ Vous avez <b>{points} points</b> valant <b>{fmt_money(points_value)}</b>.\n"
        f"Convertir en crédit sur votre portefeuille ?",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("account:redeem:"))
async def do_redeem(callback: CallbackQuery) -> None:
    points_to_use = int(callback.data.split(":")[2])
    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.username, callback.from_user.full_name,
        )
        try:
            credited = await loyalty.redeem_points(session, user.id, points_to_use)
        except ValueError as e:
            await callback.answer(str(e), show_alert=True)
            return

    await callback.message.edit_text(
        f"✅ {points_to_use} points échangés contre {fmt_money(credited)} sur votre solde !"
    )
    await callback.answer()


@router.callback_query(F.data == "account:referral_link")
async def show_referral_link(callback: CallbackQuery) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.username, callback.from_user.full_name,
        )
        ref_code = await referral.get_or_create_code(session, user.id)
        stats = await referral.get_referral_stats(session, user.id)

    me = await callback.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{ref_code}"

    await callback.message.answer(
        f"🔗 <b>Votre lien de parrainage</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"Partagez ce lien ! Vous et votre filleul recevrez un bonus à son inscription.\n"
        f"Filleuls actuels : {stats['count']}"
    )
    await callback.answer()


@router.callback_query(F.data == "account:cancel")
async def account_cancel(callback: CallbackQuery) -> None:
    await callback.message.delete()
    await callback.answer()
