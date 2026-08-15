from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from db.models import Wallet, WalletTransaction, WalletTxType
from db.session import get_session
from keyboards.admin_kb import back_to_admin_kb
from utils.filters import IsAdmin
from utils.formatting import fmt_money

router = Router(name="admin_wallet")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:wallet")
async def wallet_overview(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        total = await session.execute(select(func.coalesce(func.sum(Wallet.balance_cents), 0)))
        total_balance = total.scalar_one()

        deposits = await session.execute(
            select(func.coalesce(func.sum(WalletTransaction.amount_cents), 0))
            .where(WalletTransaction.type == WalletTxType.DEPOSIT)
        )
        total_deposits = deposits.scalar_one()

        purchases = await session.execute(
            select(func.coalesce(func.sum(WalletTransaction.amount_cents), 0))
            .where(WalletTransaction.type == WalletTxType.PURCHASE)
        )
        total_purchases = purchases.scalar_one()

    text = (
        "💰 <b>Portefeuille — vue d'ensemble</b>\n\n"
        f"Solde total cumulé des clients : {fmt_money(total_balance)}\n"
        f"Total des dépôts : {fmt_money(total_deposits)}\n"
        f"Total dépensé en achats : {fmt_money(abs(total_purchases))}\n\n"
        f"Pour créditer/débiter un client précis, utilisez le menu « Clients »."
    )
    await callback.message.edit_text(text, reply_markup=back_to_admin_kb(labels))
    await callback.answer()
