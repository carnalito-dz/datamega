"""Envoi de notifications aux admins + enregistrement en base."""
from __future__ import annotations

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db.models import Notification


async def notify_admins(bot: Bot, session: AsyncSession, ntype: str, message: str) -> None:
    session.add(Notification(type=ntype, message=message))
    await session.commit()
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, message)
        except Exception:  # noqa: BLE001
            pass
