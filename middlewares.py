"""
Middlewares aiogram.

LabelsMiddleware  — charge le dict des libellés de boutons (1 requête/update)
MaintenanceMiddleware — bloque les messages utilisateurs en mode maintenance
BanMiddleware — bloque les utilisateurs bannis
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from db.session import get_session
from services import labels as labels_service
from services import settings as settings_service


class LabelsMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with get_session() as session:
            data["labels"] = await labels_service.get_labels(session)
        return await handler(event, data)


class MaintenanceMiddleware(BaseMiddleware):
    """
    Si le mode maintenance est actif, renvoie le message maintenance aux
    utilisateurs non-admin et bloque le traitement. Les admins passent
    toujours, même en maintenance.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        import config
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        # Les admins (config + dynamiques) ne sont pas bloqués
        if user.id in config.ADMIN_IDS:
            return await handler(event, data)

        async with get_session() as session:
            all_admin_ids = await settings_service.get_all_admin_ids(session)
            if user.id in all_admin_ids:
                return await handler(event, data)

            if await settings_service.is_maintenance(session):
                from services.messages import get_message
                from services.settings import get_shop_name
                shop_name = await get_shop_name(session)
                msg = await get_message(session, "maintenance", shop_name=shop_name)
                await event.answer(msg)
                return  # bloque le handler

        return await handler(event, data)


class BanMiddleware(BaseMiddleware):
    """Bloque les utilisateurs bannis (champ is_banned sur User)."""
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        from sqlalchemy import select
        from db.models import User
        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == user.id)
            )
            db_user = result.scalar_one_or_none()
            if db_user and db_user.is_banned:
                from services.messages import get_message
                msg = await get_message(session, "banned")
                await event.answer(msg)
                return  # bloque le handler

        return await handler(event, data)
