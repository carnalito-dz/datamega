"""
Gestion des codes promo.

Types :
  - "percent" : réduction en % du prix (ex: 20 = -20%)
  - "fixed"   : réduction montant fixe en centimes (ex: 500 = -5.00$)

Idempotence : une seule utilisation par user par code (table promo_uses).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PromoCode, PromoUse


class PromoError(Exception):
    pass


async def validate_and_apply(session: AsyncSession, code_str: str,
                              user_id: int, price_cents: int) -> tuple[int, "PromoCode"]:
    """
    Valide le code promo et retourne (prix_après_réduction, promo).
    Lève PromoError si le code est invalide, expiré, épuisé ou déjà utilisé.
    """
    result = await session.execute(
        select(PromoCode).where(
            PromoCode.code == code_str.strip().upper(),
            PromoCode.is_active.is_(True),
        )
    )
    promo = result.scalar_one_or_none()

    if promo is None:
        raise PromoError("Code promo invalide ou désactivé.")

    if promo.expires_at and promo.expires_at < dt.datetime.utcnow():
        raise PromoError("Ce code promo a expiré.")

    if promo.max_uses > 0 and promo.uses_count >= promo.max_uses:
        raise PromoError("Ce code promo a atteint sa limite d'utilisation.")

    # Vérifier si cet utilisateur a déjà utilisé ce code
    used_result = await session.execute(
        select(PromoUse).where(
            PromoUse.promo_id == promo.id,
            PromoUse.user_id == user_id,
        )
    )
    if used_result.scalar_one_or_none() is not None:
        raise PromoError("Vous avez déjà utilisé ce code promo.")

    # Calculer le prix après réduction
    if promo.type == "percent":
        reduction = int(price_cents * promo.value / 100)
    else:  # fixed
        reduction = promo.value

    final_price = max(0, price_cents - reduction)
    return final_price, promo


async def record_use(session: AsyncSession, promo: PromoCode,
                     user_id: int, order_id: int | None = None) -> None:
    """Enregistre l'utilisation du code et incrémente le compteur."""
    session.add(PromoUse(
        promo_id=promo.id,
        user_id=user_id,
        order_id=order_id,
    ))
    promo.uses_count += 1
    await session.commit()


async def create_promo(session: AsyncSession, code: str, type_: str,
                       value: int, max_uses: int = 0,
                       expires_at: dt.datetime | None = None) -> PromoCode:
    promo = PromoCode(
        code=code.strip().upper(),
        type=type_,
        value=value,
        max_uses=max_uses,
        expires_at=expires_at,
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def list_promos(session: AsyncSession) -> list[PromoCode]:
    result = await session.execute(
        select(PromoCode).order_by(PromoCode.created_at.desc())
    )
    return list(result.scalars().all())


async def toggle_promo(session: AsyncSession, promo_id: int) -> PromoCode | None:
    promo = await session.get(PromoCode, promo_id)
    if promo:
        promo.is_active = not promo.is_active
        await session.commit()
    return promo


async def delete_promo(session: AsyncSession, promo_id: int) -> bool:
    promo = await session.get(PromoCode, promo_id)
    if promo:
        await session.delete(promo)
        await session.commit()
        return True
    return False
