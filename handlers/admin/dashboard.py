"""Dashboard admin — vue d'ensemble avec alertes et rafraîchissement."""
from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import func, select

from db.models import (
    Deposit, DepositStatus, Order, OrderStatus,
    Product, ProductStatus, ProductStockUnit, StockStatus, User,
    SupportMessage, SupportMessageDirection,
)
from db.session import get_session
from keyboards.admin_kb import admin_main_menu_kb
from utils.filters import IsAdmin
from utils.formatting import fmt_money

router = Router(name="admin_dashboard")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _dashboard_text() -> str:
    now = dt.datetime.utcnow()
    today = dt.datetime(now.year, now.month, now.day)
    month = dt.datetime(now.year, now.month, 1)

    async with get_session() as session:
        # Ventes aujourd'hui
        r = await session.execute(
            select(func.count(), func.coalesce(func.sum(Order.price_cents), 0))
            .where(Order.status == OrderStatus.DELIVERED, Order.delivered_at >= today)
        )
        n_today, ca_today = r.one()

        # Ventes du mois
        r2 = await session.execute(
            select(func.count(), func.coalesce(func.sum(Order.price_cents), 0))
            .where(Order.status == OrderStatus.DELIVERED, Order.delivered_at >= month)
        )
        n_month, ca_month = r2.one()

        # Clients
        r3 = await session.execute(select(func.count()).select_from(User))
        n_clients = r3.scalar_one()

        # Produits actifs
        r4 = await session.execute(
            select(func.count()).select_from(Product)
            .where(Product.status == ProductStatus.PUBLISHED)
        )
        n_active = r4.scalar_one()

        # Ruptures de stock
        avail_r = await session.execute(
            select(ProductStockUnit.product_id, func.count())
            .join(Product, Product.id == ProductStockUnit.product_id)
            .where(
                Product.status == ProductStatus.PUBLISHED,
                ProductStockUnit.status == StockStatus.AVAILABLE,
            )
            .group_by(ProductStockUnit.product_id)
        )
        with_stock = {pid for pid, _ in avail_r.all()}
        n_rupture = n_active - len(with_stock)

        # Dépôts en attente
        r5 = await session.execute(
            select(func.count()).select_from(Deposit)
            .where(Deposit.status.in_([DepositStatus.WAITING, DepositStatus.CONFIRMING]))
        )
        n_pending_deposits = r5.scalar_one()

        # Messages support non lus
        r6 = await session.execute(
            select(func.count()).select_from(SupportMessage)
            .where(
                SupportMessage.direction == SupportMessageDirection.CLIENT_TO_ADMIN,
                SupportMessage.is_read.is_(False),
            )
        )
        n_unread = r6.scalar_one()

        # Commandes échouées non remboursées
        r7 = await session.execute(
            select(func.count()).select_from(Order)
            .where(Order.status == OrderStatus.FAILED)
        )
        n_failed = r7.scalar_one()

    alerts = []
    if n_rupture > 0:
        alerts.append(f"⚠️ {n_rupture} produit(s) en rupture de stock")
    if n_pending_deposits > 0:
        alerts.append(f"⏳ {n_pending_deposits} dépôt(s) en attente de confirmation")
    if n_unread > 0:
        alerts.append(f"📩 {n_unread} message(s) support non lu(s)")
    if n_failed > 0:
        alerts.append(f"❌ {n_failed} commande(s) en échec")

    text = (
        f"📊 <b>Dashboard</b>\n\n"
        f"🗓 Ventes aujourd'hui : {n_today} — {fmt_money(ca_today)}\n"
        f"📆 Ventes du mois : {n_month} — {fmt_money(ca_month)}\n"
        f"👥 Clients : {n_clients}\n"
        f"📦 Produits actifs : {n_active}\n"
    )
    if alerts:
        text += "\n🚨 <b>Alertes</b>\n" + "\n".join(alerts)

    return text


@router.message(Command("admin"))
async def cmd_admin(message: Message, labels: dict) -> None:
    await message.answer(
        "🛠 <b>Panel admin DATA MEGA</b>",
        reply_markup=admin_main_menu_kb(labels),
    )


@router.callback_query(F.data == "admin:home")
async def admin_home(callback: CallbackQuery, labels: dict) -> None:
    await callback.message.edit_text(
        "🛠 <b>Panel admin DATA MEGA</b>",
        reply_markup=admin_main_menu_kb(labels),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:dashboard")
async def admin_dashboard(callback: CallbackQuery, labels: dict) -> None:
    text = await _dashboard_text()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Rafraîchir", callback_data="admin:dashboard")],
        [InlineKeyboardButton(
            text=labels.get("admin_back_home", "⬅️ Menu admin"),
            callback_data="admin:home",
        )],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()
