"""
Système de points de fidélité.

Paramètres configurables depuis le panel admin (table settings) :
  loyalty_points_per_dollar : points gagnés par dollar dépensé (défaut: 10)
  loyalty_points_value_cents : valeur d'un point en centimes (défaut: 1)
  loyalty_enabled : 0/1 (défaut: 1)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Wallet, WalletTransaction, WalletTxType


async def _get_setting(session: AsyncSession, key: str, default: str) -> str:
    from db.models import Setting
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def is_enabled(session: AsyncSession) -> bool:
    return await _get_setting(session, "loyalty_enabled", "1") == "1"


async def points_per_dollar(session: AsyncSession) -> int:
    return int(await _get_setting(session, "loyalty_points_per_dollar", "10"))


async def point_value_cents(session: AsyncSession) -> int:
    return int(await _get_setting(session, "loyalty_points_value_cents", "1"))


async def earn_points(session: AsyncSession, user_id: int,
                      amount_cents: int) -> int:
    """Crédite des points après un achat. Retourne le nb de points gagnés."""
    if not await is_enabled(session):
        return 0
    ppd = await points_per_dollar(session)
    points = int(amount_cents / 100 * ppd)
    if points <= 0:
        return 0

    result = await session.execute(select(Wallet).where(Wallet.user_id == user_id))
    wallet = result.scalar_one_or_none()
    if wallet:
        wallet.loyalty_points += points
        await session.commit()
    return points


async def get_balance(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """Retourne (points, valeur_en_centimes)."""
    result = await session.execute(select(Wallet).where(Wallet.user_id == user_id))
    wallet = result.scalar_one_or_none()
    points = wallet.loyalty_points if wallet else 0
    pvc = await point_value_cents(session)
    return points, points * pvc


async def redeem_points(session: AsyncSession, user_id: int,
                        points_to_use: int) -> int:
    """
    Convertit des points en crédit wallet.
    Retourne le montant crédité en centimes.
    """
    result = await session.execute(select(Wallet).where(Wallet.user_id == user_id))
    wallet = result.scalar_one_or_none()
    if not wallet or wallet.loyalty_points < points_to_use:
        raise ValueError("Points insuffisants.")

    pvc = await point_value_cents(session)
    credit_cents = points_to_use * pvc

    wallet.loyalty_points -= points_to_use
    wallet.balance_cents += credit_cents

    session.add(WalletTransaction(
        user_id=user_id,
        type=WalletTxType.BONUS,
        amount_cents=credit_cents,
        balance_after_cents=wallet.balance_cents,
        note=f"Échange de {points_to_use} points de fidélité",
    ))
    await session.commit()
    return credit_cents


async def adjust_points(session: AsyncSession, user_id: int,
                        delta: int, note: str = "") -> int:
    """Ajustement manuel des points (positif ou négatif). Retourne le nouveau solde."""
    result = await session.execute(select(Wallet).where(Wallet.user_id == user_id))
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise ValueError("Utilisateur introuvable.")
    wallet.loyalty_points = max(0, wallet.loyalty_points + delta)
    await session.commit()
    return wallet.loyalty_points
