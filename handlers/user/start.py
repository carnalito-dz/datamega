"""Handler /start — message configurable, solde bienvenue, parrainage."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from db.session import get_session
from keyboards.user_kb import main_menu_kb
from services import referral as referral_service
from services import wallet as wallet_service
from services.messages import get_message
from services.settings import get_shop_name, get_welcome_bonus_cents

router = Router(name="user_start")


@router.message(CommandStart())
async def cmd_start(message: Message, labels: dict) -> None:
    # Extraire le paramètre de parrainage si présent (/start ref_XXXXXXXX)
    args = message.text.split(maxsplit=1)
    ref_code = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]  # enlever "ref_"

    async with get_session() as session:
        user, is_new = await _get_or_create(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name,
        )

        shop_name = await get_shop_name(session)
        welcome_msg = await get_message(session, "welcome", shop_name=shop_name)

        if is_new:
            # Solde de bienvenue
            bonus = await get_welcome_bonus_cents(session)
            if bonus > 0:
                await wallet_service.credit(
                    session, user.id, bonus,
                    wallet_service.WalletTxType.BONUS,
                    note="Solde de bienvenue",
                )
                from utils.formatting import fmt_money
                welcome_msg += f"\n\n🎁 Vous avez reçu {fmt_money(bonus)} en cadeau de bienvenue !"

            # Appliquer le parrainage si présent
            if ref_code:
                try:
                    await referral_service.apply_referral(
                        session, user.id, ref_code, message.bot
                    )
                except Exception:
                    pass

            # Notifier les admins
            from services.notify import notify_admins
            from services.messages import get_message as gm
            notif = await gm(
                session, "admin_new_client",
                support=message.from_user.username or str(message.from_user.id),
                amount=str(message.from_user.id),
            )
            await notify_admins(message.bot, session, "new_client", notif)

    await message.answer(welcome_msg, reply_markup=main_menu_kb(labels))


async def _get_or_create(session, telegram_id, username, full_name):
    """Retourne (user, is_new)."""
    from sqlalchemy import select
    from db.models import User, Wallet
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
        return user, True
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
        return user, False
