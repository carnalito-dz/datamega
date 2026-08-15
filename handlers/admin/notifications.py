from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select

from db.models import Notification
from db.session import get_session
from keyboards.admin_kb import back_to_admin_kb
from utils.filters import IsAdmin
from utils.formatting import fmt_datetime

router = Router(name="admin_notifications")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:notifications")
async def list_notifications(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Notification).order_by(Notification.created_at.desc()).limit(20)
        )
        notifs = list(result.scalars().all())

    lines = ["🔔 <b>Notifications récentes</b>\n"]
    for n in notifs:
        lines.append(f"{fmt_datetime(n.created_at)} [{n.type}] {n.message}")
    if len(lines) == 1:
        lines.append("Aucune notification.")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_admin_kb(labels))
    await callback.answer()
