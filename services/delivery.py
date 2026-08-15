"""
Livraison automatique d'une unité de stock à un client.
Supporte les fichiers Telegram et les contenus texte.
Utilise les messages configurables depuis le panel admin.
"""
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db.models import Order, OrderStatus, ProductStockUnit
from services import journal, stock


async def deliver(bot: Bot, session: AsyncSession, order: Order,
                   unit: ProductStockUnit, buyer_telegram_id: int) -> bool:
    """
    Livre l'unité au client.
    En cas d'échec : libère l'unité, marque la commande FAILED, notifie les admins.
    Retourne True si succès.
    """
    from services.messages import get_message
    try:
        if unit.telegram_file_id:
            caption = await get_message(session, "delivery_file")
            await bot.send_document(
                chat_id=buyer_telegram_id,
                document=unit.telegram_file_id,
                caption=caption,
            )
        else:
            text = await get_message(
                session, "delivery_text",
                content=unit.text_content or "",
            )
            await bot.send_message(chat_id=buyer_telegram_id, text=text)

    except Exception as exc:  # noqa: BLE001
        await stock.release_unit(session, unit)
        order.status = OrderStatus.FAILED
        order.error_note = str(exc)[:500]
        await session.commit()
        await journal.log_action(
            session, None, "livraison_echec",
            f"order={order.id} unit={unit.id} err={exc}",
        )
        await _notify_admins_fail(bot, session, order, unit, exc)
        return False

    await stock.mark_sold(session, unit, buyer_telegram_id)
    order.status = OrderStatus.DELIVERED
    order.stock_unit_id = unit.id
    from datetime import datetime
    order.delivered_at = datetime.utcnow()
    await session.commit()
    await journal.log_action(
        session, None, "livraison_ok",
        f"order={order.id} unit={unit.id}",
    )
    return True


async def redeliver(bot: Bot, session: AsyncSession, order: Order,
                    buyer_telegram_id: int) -> bool:
    """
    Re-livre un fichier déjà vendu (pour la commande « re-recevoir »).
    Ne modifie pas le stock ni le solde.
    """
    if not order.stock_unit_id:
        return False

    unit = await session.get(ProductStockUnit, order.stock_unit_id)
    if not unit:
        return False

    from services.messages import get_message
    try:
        if unit.telegram_file_id:
            caption = await get_message(session, "delivery_file")
            await bot.send_document(
                chat_id=buyer_telegram_id,
                document=unit.telegram_file_id,
                caption=caption,
            )
        else:
            text = await get_message(
                session, "delivery_text",
                content=unit.text_content or "",
            )
            await bot.send_message(chat_id=buyer_telegram_id, text=text)
        return True
    except Exception:
        return False


async def _notify_admins_fail(bot: Bot, session, order, unit, exc) -> None:
    from services.messages import get_message
    from services.settings import get_dynamic_admin_ids
    msg = await get_message(
        session, "admin_delivery_fail",
        amount=str(order.id), content=str(exc)[:200],
    )
    all_ids = config.ADMIN_IDS.copy()
    try:
        all_ids |= await get_dynamic_admin_ids(session)
    except Exception:
        pass
    for admin_id in all_ids:
        try:
            await bot.send_message(admin_id, msg)
        except Exception:
            pass
