"""
Système de parrainage.

Chaque utilisateur a un code de parrainage unique (généré à l'inscription).
Quand un nouvel utilisateur s'inscrit avec un code de parrainage :
  - Le parrain reçoit un bonus configurable (setting: referral_bonus_cents)
  - Le filleul reçoit un bonus configurable (setting: referral_new_user_bonus_cents)

Le lien de parrainage est : https://t.me/<BOT_USERNAME>?start=ref_<CODE>
"""
from __future__ import annotations

import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, Wallet, WalletTransaction, WalletTxType


def generate_code() -> str:
    """Génère un code de parrainage unique de 8 caractères."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


async def get_or_create_code(session: AsyncSession, user_id: int) -> str:
    """Retourne le code de parrainage de l'utilisateur, le crée si absent."""
    user = await session.get(User, user_id)
    if not user:
        raise ValueError("Utilisateur introuvable.")
    if user.referral_code:
        return user.referral_code

    # Générer un code unique
    while True:
        code = generate_code()
        existing = await session.execute(
            select(User).where(User.referral_code == code)
        )
        if existing.scalar_one_or_none() is None:
            break

    user.referral_code = code
    await session.commit()
    return code


async def apply_referral(session: AsyncSession, new_user_id: int,
                         referral_code: str, bot) -> None:
    """
    Applique le parrainage à l'inscription d'un nouvel utilisateur.
    Crédite le parrain et le filleul si les bonus sont configurés.
    """
    from db.models import Setting
    from services.wallet import credit

    # Trouver le parrain
    result = await session.execute(
        select(User).where(User.referral_code == referral_code.upper())
    )
    referrer = result.scalar_one_or_none()
    if referrer is None or referrer.id == new_user_id:
        return

    new_user = await session.get(User, new_user_id)
    if not new_user or new_user.referred_by_id:
        return  # déjà parrainé

    # Marquer le parrainage
    new_user.referred_by_id = referrer.id
    await session.commit()

    # Bonus parrain
    ref_bonus_result = await session.execute(
        select(Setting).where(Setting.key == "referral_bonus_cents")
    )
    ref_bonus_row = ref_bonus_result.scalar_one_or_none()
    ref_bonus = int(ref_bonus_row.value) if ref_bonus_row else 0

    # Bonus filleul
    new_bonus_result = await session.execute(
        select(Setting).where(Setting.key == "referral_new_user_bonus_cents")
    )
    new_bonus_row = new_bonus_result.scalar_one_or_none()
    new_bonus = int(new_bonus_row.value) if new_bonus_row else 0

    if ref_bonus > 0:
        await credit(session, referrer.id, ref_bonus, WalletTxType.REFERRAL,
                     note=f"Parrainage de @{new_user.username or new_user_id}")
        try:
            from utils.formatting import fmt_money
            await bot.send_message(
                referrer.telegram_id,
                f"🎉 Quelqu'un a rejoint via votre lien de parrainage !\n"
                f"Vous avez reçu {fmt_money(ref_bonus)} sur votre solde.",
            )
        except Exception:
            pass

    if new_bonus > 0:
        await credit(session, new_user_id, new_bonus, WalletTxType.REFERRAL,
                     note="Bonus parrainage à l'inscription")


async def get_referral_stats(session: AsyncSession, user_id: int) -> dict:
    """Retourne les stats de parrainage d'un utilisateur."""
    result = await session.execute(
        select(User).where(User.referred_by_id == user_id)
    )
    referrals = list(result.scalars().all())
    return {
        "count": len(referrals),
        "users": referrals,
    }
