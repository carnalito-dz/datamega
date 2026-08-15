"""
Messagerie bidirectionnelle admin ↔ client.

- Le client envoie un message depuis le bot → stocké + notifié aux admins
- L'admin répond depuis /admin → Notifications → Messagerie → client notifié
- Historique consultable des deux côtés
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SupportMessage, SupportMessageDirection, User


async def send_from_client(session: AsyncSession, user_id: int,
                            text: str, bot) -> SupportMessage:
    """Client → Admin : enregistre et notifie tous les admins."""
    msg = SupportMessage(
        user_id=user_id,
        direction=SupportMessageDirection.CLIENT_TO_ADMIN,
        text=text,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    # Notifier les admins
    user = await session.get(User, user_id)
    import config
    from services.settings import get_dynamic_admin_ids
    all_admin_ids = config.ADMIN_IDS.copy()
    try:
        all_admin_ids |= await get_dynamic_admin_ids(session)
    except Exception:
        pass

    notif_text = (
        f"📩 <b>Message support</b>\n"
        f"De : @{user.username or '?'} (<code>{user.telegram_id}</code>)\n\n"
        f"{text}\n\n"
        f"<i>Répondez via /admin → 💬 Messagerie</i>"
    )
    for admin_id in all_admin_ids:
        try:
            await bot.send_message(admin_id, notif_text)
        except Exception:
            pass

    return msg


async def send_from_admin(session: AsyncSession, user_id: int,
                           admin_telegram_id: int, text: str, bot) -> SupportMessage:
    """Admin → Client : enregistre et envoie au client."""
    msg = SupportMessage(
        user_id=user_id,
        direction=SupportMessageDirection.ADMIN_TO_CLIENT,
        admin_telegram_id=admin_telegram_id,
        text=text,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)

    user = await session.get(User, user_id)
    try:
        await bot.send_message(
            user.telegram_id,
            f"💬 <b>Réponse du support</b>\n\n{text}",
        )
    except Exception:
        pass

    return msg


async def get_conversation(session: AsyncSession, user_id: int,
                            limit: int = 20) -> list[SupportMessage]:
    """Retourne les derniers messages du fil de support d'un client."""
    result = await session.execute(
        select(SupportMessage)
        .where(SupportMessage.user_id == user_id)
        .order_by(SupportMessage.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def get_unread_threads(session: AsyncSession) -> list[tuple[int, int]]:
    """
    Retourne les fils avec des messages non lus côté admin.
    Retourne [(user_id, nb_non_lus), ...].
    """
    from sqlalchemy import func
    result = await session.execute(
        select(SupportMessage.user_id, func.count().label("n"))
        .where(
            SupportMessage.direction == SupportMessageDirection.CLIENT_TO_ADMIN,
            SupportMessage.is_read.is_(False),
        )
        .group_by(SupportMessage.user_id)
        .order_by(func.count().desc())
    )
    return list(result.all())


async def mark_thread_read(session: AsyncSession, user_id: int) -> None:
    """Marque tous les messages d'un client comme lus."""
    from sqlalchemy import update
    await session.execute(
        update(SupportMessage)
        .where(
            SupportMessage.user_id == user_id,
            SupportMessage.direction == SupportMessageDirection.CLIENT_TO_ADMIN,
            SupportMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await session.commit()


async def get_all_threads_preview(session: AsyncSession) -> list[dict]:
    """
    Retourne un aperçu de tous les fils de support (dernier message + stats).
    """
    from sqlalchemy import func
    from db.models import User

    # Sous-requête : dernier message par user
    result = await session.execute(
        select(
            SupportMessage.user_id,
            func.max(SupportMessage.created_at).label("last_at"),
            func.count().label("total"),
        )
        .group_by(SupportMessage.user_id)
        .order_by(func.max(SupportMessage.created_at).desc())
    )
    threads = []
    for user_id, last_at, total in result.all():
        user = await session.get(User, user_id)
        # Dernier message
        last_msg_result = await session.execute(
            select(SupportMessage)
            .where(SupportMessage.user_id == user_id)
            .order_by(SupportMessage.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()
        # Non lus
        unread_result = await session.execute(
            select(func.count()).select_from(SupportMessage).where(
                SupportMessage.user_id == user_id,
                SupportMessage.direction == SupportMessageDirection.CLIENT_TO_ADMIN,
                SupportMessage.is_read.is_(False),
            )
        )
        unread = unread_result.scalar_one()
        threads.append({
            "user": user,
            "last_at": last_at,
            "total": total,
            "unread": unread,
            "last_text": last_msg.text[:60] if last_msg else "",
            "last_direction": last_msg.direction if last_msg else None,
        })
    return threads
