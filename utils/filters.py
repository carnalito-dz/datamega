"""Filtres aiogram : IsAdmin (dynamique) et MatchesLabel."""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject

import config


class IsAdmin(BaseFilter):
    """
    Vérifie que l'utilisateur est admin.
    Consulte les admins dynamiques (panel) en plus de config.ADMIN_IDS.
    """
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if not user:
            return False
        if user.id in config.ADMIN_IDS:
            return True
        from db.session import get_session
        from services import settings as settings_service
        async with get_session() as session:
            all_ids = await settings_service.get_all_admin_ids(session)
        return user.id in all_ids


class MatchesLabel(BaseFilter):
    """
    Filtre pour les boutons reply keyboard renommables.
    Compare le texte du message au libellé actuel injecté par LabelsMiddleware.
    """
    def __init__(self, key: str) -> None:
        self.key = key

    async def __call__(self, message: Message,
                       labels: dict[str, str] | None = None) -> bool:
        if not message.text or not labels:
            return False
        return message.text == labels.get(self.key)
