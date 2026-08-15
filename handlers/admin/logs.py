from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select

from db.models import AdminLog
from db.session import get_session
from keyboards.admin_kb import back_to_admin_kb
from utils.filters import IsAdmin
from utils.formatting import fmt_datetime

router = Router(name="admin_logs")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:logs")
async def show_logs(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(AdminLog).order_by(AdminLog.created_at.desc()).limit(25)
        )
        logs = list(result.scalars().all())

    lines = ["📜 <b>Journal</b>\n"]
    for log in logs:
        who = log.admin_id or "système"
        lines.append(f"{fmt_datetime(log.created_at)} — {log.action} ({who}) — {log.details or ''}")
    if len(lines) == 1:
        lines.append("Journal vide.")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_admin_kb(labels))
    await callback.answer()
