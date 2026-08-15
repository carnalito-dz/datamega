"""
Panel admin — Clients.
Recherche, fiche détaillée, crédit/débit, ban/déblocage,
historique achats, ajustement points fidélité.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select

from db.models import Order, OrderStatus, Product, User, WalletTxType
from db.session import get_session
from services import wallet as wallet_service, loyalty
from services.journal import log_action
from utils.filters import IsAdmin
from utils.formatting import fmt_datetime, fmt_money
from utils.money import InvalidAmount, parse_usd_to_cents
from utils.states import AdminReplyFlow, ClientSearchFlow, ClientWalletFlow, ClientLoyaltyFlow

router = Router(name="admin_clients")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _back_kb(labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("admin_back_home", "⬅️ Menu admin"),
            callback_data="admin:home",
        )]
    ])


def _client_detail_kb(telegram_id: int, is_banned: bool, labels: dict) -> InlineKeyboardMarkup:
    ban_text = "🔓 Débloquer" if is_banned else "🚫 Bannir"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Créditer", callback_data=f"admin:client:credit:{telegram_id}"),
         InlineKeyboardButton(text="➖ Débiter",  callback_data=f"admin:client:debit:{telegram_id}")],
        [InlineKeyboardButton(text="⭐ Ajuster points", callback_data=f"admin:client:loyalty:{telegram_id}")],
        [InlineKeyboardButton(text="📦 Historique achats", callback_data=f"admin:client:orders:{telegram_id}")],
        [InlineKeyboardButton(text="💬 Envoyer message", callback_data=f"admin:client:message:{telegram_id}")],
        [InlineKeyboardButton(text=ban_text, callback_data=f"admin:client:toggleban:{telegram_id}")],
        [InlineKeyboardButton(text="⬅️ Clients", callback_data="admin:clients")],
    ])


@router.callback_query(F.data == "admin:clients")
async def clients_menu(callback: CallbackQuery, state: FSMContext, labels: dict) -> None:
    await state.set_state(ClientSearchFlow.waiting_query)
    await callback.message.edit_text(
        "👥 <b>Clients</b>\n\n"
        "Envoyez l'ID Telegram ou le @username du client à consulter :",
        reply_markup=_back_kb(labels),
    )
    await callback.answer()


@router.message(ClientSearchFlow.waiting_query)
async def search_client(message: Message, state: FSMContext, labels: dict) -> None:
    query = message.text.strip().lstrip("@")
    async with get_session() as session:
        if query.isdigit():
            r = await session.execute(
                select(User).where(User.telegram_id == int(query))
            )
        else:
            r = await session.execute(
                select(User).where(User.username == query)
            )
        user = r.scalar_one_or_none()

        if not user:
            await message.answer("❌ Client introuvable.")
            return

        w = await wallet_service.get_wallet(session, user.id)
        orders_r = await session.execute(
            select(Order).where(
                Order.user_id == user.id,
                Order.status == OrderStatus.DELIVERED,
            )
        )
        n_orders = len(list(orders_r.scalars().all()))
        points, _ = await loyalty.get_balance(session, user.id)

    await state.clear()
    ban_status = "🚫 Banni" if user.is_banned else "✅ Actif"
    await message.answer(
        f"👤 <b>Client</b>\n\n"
        f"ID : <code>{user.telegram_id}</code>\n"
        f"Username : @{user.username or '—'}\n"
        f"Solde : {fmt_money(w.balance_cents)}\n"
        f"Points fidélité : {points}\n"
        f"Achats : {n_orders}\n"
        f"Statut : {ban_status}\n"
        f"Membre depuis : {fmt_datetime(user.created_at)}",
        reply_markup=_client_detail_kb(user.telegram_id, user.is_banned, labels),
    )


# ── Crédit / Débit ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:client:credit:"))
async def start_credit(callback: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(callback.data.split(":")[3])
    await state.update_data(target_telegram_id=tg_id, op="credit")
    await state.set_state(ClientWalletFlow.choosing_amount)
    await callback.message.answer("Montant à créditer (USD, ex: 10.50) :")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:client:debit:"))
async def start_debit(callback: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(callback.data.split(":")[3])
    await state.update_data(target_telegram_id=tg_id, op="debit")
    await state.set_state(ClientWalletFlow.choosing_amount)
    await callback.message.answer("Montant à débiter (USD, ex: 5.00) :")
    await callback.answer()


@router.message(ClientWalletFlow.choosing_amount)
async def receive_amount(message: Message, state: FSMContext) -> None:
    try:
        amount_cents = parse_usd_to_cents(message.text)
    except InvalidAmount:
        await message.answer("Montant invalide, réessayez.")
        return
    await state.update_data(amount_cents=amount_cents)
    await state.set_state(ClientWalletFlow.choosing_note)
    await message.answer("Note (ou « - » pour aucune) :")


@router.message(ClientWalletFlow.choosing_note)
async def receive_note(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tg_id = data["target_telegram_id"]
    amount_cents = data["amount_cents"]
    op = data["op"]
    note = None if message.text.strip() == "-" else message.text.strip()

    async with get_session() as session:
        r = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = r.scalar_one_or_none()
        if not user:
            await message.answer("Client introuvable.")
            await state.clear()
            return

        try:
            if op == "credit":
                w = await wallet_service.credit(
                    session, user.id, amount_cents, WalletTxType.ADMIN_CREDIT, note
                )
            else:
                w = await wallet_service.debit(
                    session, user.id, amount_cents, WalletTxType.ADMIN_DEBIT, note
                )
        except wallet_service.InsufficientBalance:
            await message.answer("❌ Solde insuffisant.")
            await state.clear()
            return

        await log_action(
            session, message.from_user.id, f"wallet_{op}",
            f"user={tg_id} amount_cents={amount_cents}",
        )

    await state.clear()
    sign = "+" if op == "credit" else "-"
    await message.answer(
        f"✅ Opération effectuée.\n"
        f"Variation : {sign}{fmt_money(amount_cents)}\n"
        f"Nouveau solde : {fmt_money(w.balance_cents)}"
    )
    try:
        await message.bot.send_message(
            tg_id,
            f"💰 Votre solde a été mis à jour par l'administration "
            f"({sign}{fmt_money(amount_cents)}).\n"
            f"Nouveau solde : {fmt_money(w.balance_cents)}",
        )
    except Exception:
        pass


# ── Ban / Déblocage ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:client:toggleban:"))
async def toggle_ban(callback: CallbackQuery, labels: dict) -> None:
    tg_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        r = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = r.scalar_one_or_none()
        if not user:
            await callback.answer("Client introuvable.", show_alert=True)
            return
        user.is_banned = not user.is_banned
        await session.commit()
        await log_action(
            session, callback.from_user.id,
            "client_banni" if user.is_banned else "client_debanni",
            str(tg_id),
        )

    status = "banni" if user.is_banned else "débanni"
    await callback.answer(f"Client {status}.", show_alert=True)

    # Notifier le client si débanni
    if not user.is_banned:
        try:
            await callback.bot.send_message(
                tg_id, "✅ Votre compte a été réactivé. Bienvenue à nouveau !"
            )
        except Exception:
            pass


# ── Historique achats ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:client:orders:"))
async def client_orders(callback: CallbackQuery) -> None:
    tg_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        r = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = r.scalar_one_or_none()
        if not user:
            await callback.answer("Introuvable.", show_alert=True)
            return

        orders_r = await session.execute(
            select(Order, Product)
            .join(Product, Order.product_id == Product.id)
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
            .limit(20)
        )
        rows = list(orders_r.all())

    if not rows:
        await callback.answer("Aucune commande.", show_alert=True)
        return

    lines = [f"📦 <b>Commandes de @{user.username or tg_id}</b>\n"]
    for order, product in rows:
        status_icon = {
            "delivered": "✅", "failed": "❌", "refunded": "↩️",
            "paid": "💳", "pending": "⏳",
        }.get(order.status.value, "?")
        lines.append(
            f"{status_icon} #{order.id} — {order.quantity}x {product.name} — "
            f"{fmt_money(order.price_cents)} — {fmt_datetime(order.created_at)}"
        )

    await callback.message.answer("\n".join(lines))
    await callback.answer()


# ── Message direct admin → client ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:client:message:"))
async def start_client_message(callback: CallbackQuery, state: FSMContext) -> None:
    tg_id = int(callback.data.split(":")[3])
    await state.set_state(AdminReplyFlow_inline := AdminReplyFlow.writing_reply)
    await state.update_data(reply_to_tg_id=tg_id)
    await callback.message.answer(
        "✍️ Écrivez votre message (/annuler pour abandonner) :"
    )
    await callback.answer()



@router.message(AdminReplyFlow.writing_reply, F.text == "/annuler")
async def cancel_client_msg(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Message annulé.")


@router.message(AdminReplyFlow.writing_reply)
async def send_client_msg(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tg_id = data.get("reply_to_tg_id")
    user_id = data.get("reply_to_user_id")  # depuis messaging.py
    await state.clear()

    target_tg_id = tg_id or None
    if not target_tg_id and user_id:
        async with get_session() as session:
            user = await session.get(User, user_id)
            if user:
                target_tg_id = user.telegram_id

    if not target_tg_id:
        await message.answer("Destinataire introuvable.")
        return

    try:
        await message.bot.send_message(
            target_tg_id,
            f"💬 <b>Message de l'administration</b>\n\n{message.text}",
        )
        await message.answer("✅ Message envoyé.")
    except Exception as e:
        await message.answer(f"❌ Erreur : {e}")
