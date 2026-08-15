from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

import config
from db.models import Deposit, DepositStatus, WalletTransaction
from db.session import get_session
from keyboards.user_kb import deposit_amount_kb, deposit_currency_kb
from utils.filters import MatchesLabel
from services import nowpayments
from services import settings as settings_service
from services.wallet import get_or_create_user, get_wallet
from utils.formatting import fmt_datetime, fmt_money
from utils.money import InvalidAmount, parse_usd_to_cents
from utils.money import dollars_to_cents
from utils.states import DepositFlow

router = Router(name="user_wallet")


@router.message(MatchesLabel("menu_wallet"))
async def show_wallet(message: Message, labels: dict[str, str]) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.username, message.from_user.full_name
        )
        w = await get_wallet(session, user.id)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Recharger", callback_data="wallet:deposit")],
        [InlineKeyboardButton(text="📜 Historique", callback_data="wallet:history")],
    ])
    await message.answer(
        f"💰 Votre solde : <b>{fmt_money(w.balance_cents)}</b>\n"
        f"⭐ Points fidélité : <b>{w.loyalty_points}</b>",
        reply_markup=kb,
    )


@router.callback_query(F.data == "wallet:history")
async def wallet_history(callback: CallbackQuery) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.username, callback.from_user.full_name
        )
        result = await session.execute(
            select(WalletTransaction)
            .where(WalletTransaction.user_id == user.id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(15)
        )
        txs = list(result.scalars().all())
    if not txs:
        await callback.answer("Aucune transaction pour le moment.", show_alert=True)
        return
    lines = ["📜 <b>Dernières transactions</b>\n"]
    for tx in txs:
        sign = "+" if tx.amount_cents >= 0 else ""
        lines.append(f"{fmt_datetime(tx.created_at)} — {tx.type.value} : {sign}{fmt_money(tx.amount_cents)}")
    await callback.message.answer("\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "wallet:deposit")
async def start_deposit(callback: CallbackQuery, state: FSMContext, labels: dict[str, str]) -> None:
    async with get_session() as session:
        presets = await settings_service.get_deposit_presets(session)
        enabled = await settings_service.is_nowpayments_enabled(session)
    if not enabled:
        await callback.answer("Les dépôts sont temporairement désactivés.", show_alert=True)
        return
    await state.set_state(DepositFlow.choosing_amount)
    await callback.message.answer(
        "Choisissez un montant à recharger :", reply_markup=deposit_amount_kb(presets, labels)
    )
    await callback.answer()


@router.callback_query(DepositFlow.choosing_amount, F.data.startswith("deposit:amount:"))
async def choose_preset_amount(callback: CallbackQuery, state: FSMContext) -> None:
    amount_cents = dollars_to_cents(callback.data.split(":")[2])
    await state.update_data(amount_cents=amount_cents)
    async with get_session() as session:
        enabled_cryptos = await settings_service.get_enabled_cryptos(session)
    await state.set_state(DepositFlow.choosing_currency)
    await callback.message.answer(
        f"Montant : {fmt_money(amount_cents)}\nChoisissez la crypto de paiement :",
        reply_markup=deposit_currency_kb(enabled_cryptos),
    )
    await callback.answer()


@router.callback_query(DepositFlow.choosing_amount, F.data == "deposit:custom")
async def ask_custom_amount(callback: CallbackQuery, state: FSMContext) -> None:
    async with get_session() as session:
        min_deposit = await settings_service.get_min_deposit_usd(session)
    await state.set_state(DepositFlow.choosing_custom_amount)
    await callback.message.answer(
        f"Envoyez le montant en USD à recharger (minimum {min_deposit}$)."
    )
    await callback.answer()


@router.message(DepositFlow.choosing_custom_amount)
async def receive_custom_amount(message: Message, state: FSMContext) -> None:
    try:
        amount_cents = parse_usd_to_cents(message.text)
    except InvalidAmount:
        await message.answer("Montant invalide. Réessayez (exemple : 25).")
        return
    async with get_session() as session:
        min_deposit = await settings_service.get_min_deposit_usd(session)
    if amount_cents < int(min_deposit * 100):
        await message.answer(f"Le montant minimum est {min_deposit:.2f}$.")
        return
    await state.update_data(amount_cents=amount_cents)
    async with get_session() as session:
        enabled_cryptos = await settings_service.get_enabled_cryptos(session)
    await state.set_state(DepositFlow.choosing_currency)
    await message.answer(
        f"Montant : {fmt_money(amount_cents)}\nChoisissez la crypto de paiement :",
        reply_markup=deposit_currency_kb(enabled_cryptos),
    )


@router.callback_query(DepositFlow.choosing_currency, F.data.startswith("deposit:currency:"))
async def choose_currency(callback: CallbackQuery, state: FSMContext) -> None:
    currency = callback.data.split(":")[2]
    data = await state.get_data()
    amount_cents = data["amount_cents"]

    if not config.NOWPAYMENTS_API_KEY:
        await callback.message.answer(
            "⚠️ Les paiements crypto ne sont pas encore configurés. Contactez le support."
        )
        await callback.answer()
        await state.clear()
        return

    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.username, callback.from_user.full_name
        )
        order_id = nowpayments.new_order_id()
        try:
            # NOWPayments attend le montant en dollars (nombre décimal) ;
            # amount_cents reste la source de vérité stockée en base.
            payment = await nowpayments.create_payment(
                amount_cents / 100, currency, order_id
            )
        except nowpayments.NowPaymentsError as exc:
            await callback.message.answer(f"❌ Erreur lors de la création du paiement : {exc}")
            await callback.answer()
            await state.clear()
            return

        deposit = Deposit(
            user_id=user.id,
            payment_id=str(payment["payment_id"]),
            currency=currency,
            amount_usd_cents=amount_cents,
            pay_amount=str(payment["pay_amount"]) if payment.get("pay_amount") is not None else None,
            pay_address=payment.get("pay_address"),
            status=DepositStatus.WAITING,
        )
        session.add(deposit)
        await session.commit()

    address = payment.get("pay_address", "—")
    pay_amount = payment.get("pay_amount", "—")
    async with get_session() as session:
        from services.messages import get_message as gm
        caption = await gm(
            session, "deposit_instructions",
            pay_amount=pay_amount, currency=currency.upper(), address=address,
        )
    qr = nowpayments.make_qr_png(address)
    from aiogram.types import BufferedInputFile
    await callback.message.answer_photo(
        BufferedInputFile(qr.read(), filename="qr.png"), caption=caption
    )
    await callback.answer()
    await state.clear()
