"""
Service portefeuille : lecture, crédit, débit.
Chaque mouvement génère une ligne wallet_transactions.

Sécurité concurrence : credit() et debit() utilisent des UPDATE conditionnels
atomiques — jamais de lire-puis-écrire — pour éviter les lost updates même
sous PostgreSQL avec plusieurs connexions simultanées.
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, Wallet, WalletTransaction, WalletTxType


class InsufficientBalance(Exception):
    pass


async def get_or_create_user(session: AsyncSession, telegram_id: int,
                              username: str | None,
                              full_name: str | None) -> User:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, username=username, full_name=full_name)
        session.add(user)
        await session.flush()
        wallet = Wallet(user_id=user.id, balance_cents=0)
        session.add(wallet)
        await session.commit()
        await session.refresh(user)
    else:
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if full_name and user.full_name != full_name:
            user.full_name = full_name
            changed = True
        if changed:
            await session.commit()
    return user


async def get_wallet(session: AsyncSession, user_id: int) -> Wallet:
    result = await session.execute(
        select(Wallet).where(Wallet.user_id == user_id)
    )
    wallet = result.scalar_one_or_none()
    if wallet is None:
        wallet = Wallet(user_id=user_id, balance_cents=0)
        session.add(wallet)
        await session.commit()
        await session.refresh(wallet)
    return wallet


async def credit(session: AsyncSession, user_id: int, amount_cents: int,
                 tx_type: WalletTxType, note: str | None = None) -> Wallet:
    if amount_cents <= 0:
        raise ValueError("Le montant à créditer doit être positif.")
    await get_wallet(session, user_id)
    await session.execute(
        update(Wallet)
        .where(Wallet.user_id == user_id)
        .values(balance_cents=Wallet.balance_cents + amount_cents)
    )
    await session.commit()
    wallet = await get_wallet(session, user_id)
    session.add(WalletTransaction(
        user_id=user_id,
        type=tx_type,
        amount_cents=amount_cents,
        balance_after_cents=wallet.balance_cents,
        note=note,
    ))
    await session.commit()
    return wallet


async def debit(session: AsyncSession, user_id: int, amount_cents: int,
                tx_type: WalletTxType, note: str | None = None) -> Wallet:
    if amount_cents <= 0:
        raise ValueError("Le montant à débiter doit être positif.")
    await get_wallet(session, user_id)
    result = await session.execute(
        update(Wallet)
        .where(Wallet.user_id == user_id, Wallet.balance_cents >= amount_cents)
        .values(balance_cents=Wallet.balance_cents - amount_cents)
    )
    await session.commit()
    if result.rowcount == 0:
        raise InsufficientBalance("Solde insuffisant.")
    wallet = await get_wallet(session, user_id)
    session.add(WalletTransaction(
        user_id=user_id,
        type=tx_type,
        amount_cents=-amount_cents,
        balance_after_cents=wallet.balance_cents,
        note=note,
    ))
    await session.commit()
    return wallet
