"""Journalisation des actions admin et des événements système."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AdminLog


async def log_action(session: AsyncSession, admin_id: int | None,
                      action: str, details: str | None = None) -> None:
    session.add(AdminLog(admin_id=admin_id, action=action, details=details))
    await session.commit()
