"""
Logique de crédit d'un dépôt — partagée entre webhook IPN et tâche de fond.
Utilise les messages configurables depuis le panel admin.
"""
from __future__ import annotations

from aiogram import Bot
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db.models import Deposit, DepositStatus, User, WalletTxType
from services import journal, wallet
from services.messages import get_message
from utils.formatting import fmt_money

FINAL_PAID_STATUSES = {"finished", "confirmed"}
VALID_STATUSES = {s.value for s in DepositStatus}


async def apply_status_update(session: AsyncSession, deposit: Deposit,
                               payment_status: str, bot: Bot) -> bool:
    if payment_status in VALID_STATUSES:
        deposit.status = DepositStatus(payment_status)
        await session.commit()

    if payment_status not in FINAL_PAID_STATUSES:
        return False

    claim = await session.execute(
        update(Deposit)
        .where(Deposit.id == deposit.id, Deposit.credited.is_(False))
        .values(credited=True)
    )
    await session.commit()

    if claim.rowcount == 0:
        return False

    user = await session.get(User, deposit.user_id)
    w = await wallet.credit(
        session, deposit.user_id, deposit.amount_usd_cents, WalletTxType.DEPOSIT,
        note=f"Dépôt crypto {deposit.currency} — paiement {deposit.payment_id}",
    )
    await journal.log_action(
        session, None, "depot_credite",
        f"user={user.telegram_id} amount_cents={deposit.amount_usd_cents} "
        f"payment_id={deposit.payment_id}",
    )

    # Message client configurable
    client_msg = await get_message(
        session, "deposit_confirmed",
        amount=fmt_money(deposit.amount_usd_cents),
        balance=fmt_money(w.balance_cents),
    )
    try:
        await bot.send_message(user.telegram_id, client_msg)
    except Exception:  # noqa: BLE001
        pass

    # Notification admins configurable
    admin_msg = await get_message(
        session, "deposit_confirmed_admin",
        amount=fmt_money(deposit.amount_usd_cents),
        support=user.username or str(user.telegram_id),
    )

    all_admin_ids = config.ADMIN_IDS.copy()
    try:
        from services.settings import get_dynamic_admin_ids
        all_admin_ids |= await get_dynamic_admin_ids(session)
    except Exception:  # noqa: BLE001
        pass

    for admin_id in all_admin_ids:
        try:
            await bot.send_message(admin_id, admin_msg)
        except Exception:  # noqa: BLE001
            pass

    return True
