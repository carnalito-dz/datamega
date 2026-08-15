from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from db.models import Deposit, Order, OrderStatus, Product
from db.session import get_session
from keyboards.admin_kb import back_to_admin_kb
from utils.filters import IsAdmin
from utils.formatting import fmt_money

router = Router(name="admin_stats")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:stats")
async def show_stats(callback: CallbackQuery, labels: dict[str, str]) -> None:
    now = dt.datetime.utcnow()
    day_start = dt.datetime(now.year, now.month, now.day)
    week_start = day_start - dt.timedelta(days=now.weekday())
    month_start = dt.datetime(now.year, now.month, 1)

    async with get_session() as session:
        async def ca_since(since):
            r = await session.execute(
                select(func.coalesce(func.sum(Order.price_cents), 0), func.count())
                .where(Order.status == OrderStatus.DELIVERED, Order.delivered_at >= since)
            )
            return r.one()

        ca_day, n_day = await ca_since(day_start)
        ca_week, n_week = await ca_since(week_start)
        ca_month, n_month = await ca_since(month_start)

        top = await session.execute(
            select(Product.name, func.count(Order.id).label("n"))
            .join(Order, Order.product_id == Product.id)
            .where(Order.status == OrderStatus.DELIVERED)
            .group_by(Product.id)
            .order_by(func.count(Order.id).desc())
            .limit(5)
        )
        top_products = list(top.all())

        deposits_total = await session.execute(
            select(func.coalesce(func.sum(Deposit.amount_usd_cents), 0)).where(Deposit.credited.is_(True))
        )
        total_deposits = deposits_total.scalar_one()

    lines = [
        "📈 <b>Statistiques</b>\n",
        f"CA jour : {fmt_money(ca_day)} ({n_day} ventes)",
        f"CA semaine : {fmt_money(ca_week)} ({n_week} ventes)",
        f"CA mois : {fmt_money(ca_month)} ({n_month} ventes)",
        f"Total dépôts confirmés : {fmt_money(total_deposits)}",
        "\n🏆 <b>Produits les plus vendus</b>",
    ]
    if top_products:
        for name, n in top_products:
            lines.append(f"{name} — {n} vente(s)")
    else:
        lines.append("Aucune vente pour le moment.")

    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_admin_kb(labels))
    await callback.answer()
