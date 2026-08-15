"""Panel admin — Commandes avec filtrage, remboursement manuel, re-livraison."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select

from db.models import Order, OrderStatus, Product, User
from db.session import get_session
from services import delivery as delivery_service
from services.journal import log_action
from services.wallet import credit, WalletTxType
from utils.filters import IsAdmin
from utils.formatting import fmt_datetime, fmt_money

router = Router(name="admin_orders")
router.callback_query.filter(IsAdmin())


def _back_kb(labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("admin_back_home", "⬅️ Menu admin"),
            callback_data="admin:home",
        )]
    ])


def _filter_kb(current: str, labels: dict) -> InlineKeyboardMarkup:
    statuses = [
        ("Toutes", "all"), ("✅ Livrées", "delivered"),
        ("❌ Échouées", "failed"), ("↩️ Remboursées", "refunded"),
    ]
    rows = []
    row = []
    for label, value in statuses:
        text = f"[{label}]" if value == current else label
        row.append(InlineKeyboardButton(
            text=text, callback_data=f"admin:orders:filter:{value}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text=labels.get("admin_back_home", "⬅️ Menu admin"),
        callback_data="admin:home",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_orders(callback: CallbackQuery, filter_: str, labels: dict) -> None:
    async with get_session() as session:
        q = (
            select(Order, Product, User)
            .join(Product, Order.product_id == Product.id)
            .join(User, Order.user_id == User.id)
            .order_by(Order.created_at.desc())
            .limit(20)
        )
        if filter_ != "all":
            q = q.where(Order.status == OrderStatus(filter_))
        result = await session.execute(q)
        rows = list(result.all())

    icons = {
        "delivered": "✅", "failed": "❌", "refunded": "↩️",
        "paid": "💳", "pending": "⏳",
    }
    lines = [f"🧾 <b>Commandes</b> [{filter_}]\n"]
    order_rows = []
    for order, product, user in rows:
        icon = icons.get(order.status.value, "?")
        lines.append(
            f"{icon} #{order.id} — {order.quantity}x {product.name} — "
            f"{fmt_money(order.price_cents)} — "
            f"@{user.username or user.telegram_id} — "
            f"{fmt_datetime(order.created_at)}"
        )
        # Boutons d'action pour les commandes échouées/livrées
        if order.status in (OrderStatus.FAILED, OrderStatus.DELIVERED):
            action_btns = []
            if order.status == OrderStatus.FAILED:
                action_btns.append(InlineKeyboardButton(
                    text=f"↩️ Remb. #{order.id}",
                    callback_data=f"admin:order:refund:{order.id}",
                ))
            if order.stock_unit_id:
                action_btns.append(InlineKeyboardButton(
                    text=f"🔄 Re-livrer #{order.id}",
                    callback_data=f"admin:order:redeliver:{order.id}",
                ))
            if action_btns:
                order_rows.append(action_btns)

    if len(lines) == 1:
        lines.append("Aucune commande.")

    # Combiner le texte filtré + les boutons d'action
    filter_rows = _filter_kb(filter_, labels).inline_keyboard
    all_rows = order_rows[:5] + filter_rows  # max 5 boutons action
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=all_rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:orders")
async def list_orders(callback: CallbackQuery, labels: dict) -> None:
    await _show_orders(callback, "all", labels)


@router.callback_query(F.data.startswith("admin:orders:filter:"))
async def filter_orders(callback: CallbackQuery, labels: dict) -> None:
    filter_ = callback.data.split(":")[3]
    await _show_orders(callback, filter_, labels)


@router.callback_query(F.data.startswith("admin:order:refund:"))
async def manual_refund(callback: CallbackQuery, labels: dict) -> None:
    order_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        order = await session.get(Order, order_id)
        if not order:
            await callback.answer("Commande introuvable.", show_alert=True)
            return
        if order.status == OrderStatus.REFUNDED:
            await callback.answer("Déjà remboursée.", show_alert=True)
            return

        await credit(
            session, order.user_id, order.price_cents,
            WalletTxType.REFUND,
            note=f"Remboursement manuel commande #{order_id}",
        )
        order.status = OrderStatus.REFUNDED
        await session.commit()
        await log_action(
            session, callback.from_user.id, "remboursement_manuel", str(order_id)
        )

        # Notifier le client
        from db.models import User
        from sqlalchemy import select as sa_select
        user_r = await session.execute(
            sa_select(User).where(User.id == order.user_id)
        )
        user = user_r.scalar_one_or_none()
        if user:
            try:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"↩️ La commande #{order_id} a été remboursée.\n"
                    f"Montant : {fmt_money(order.price_cents)}",
                )
            except Exception:
                pass

    await callback.answer(f"Commande #{order_id} remboursée.", show_alert=True)
    await list_orders(callback, labels)


@router.callback_query(F.data.startswith("admin:order:redeliver:"))
async def manual_redeliver(callback: CallbackQuery, labels: dict) -> None:
    order_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        order = await session.get(Order, order_id)
        if not order or not order.stock_unit_id:
            await callback.answer("Impossible de re-livrer.", show_alert=True)
            return

        from db.models import User
        from sqlalchemy import select as sa_select
        user_r = await session.execute(
            sa_select(User).where(User.id == order.user_id)
        )
        user = user_r.scalar_one_or_none()
        if not user:
            await callback.answer("Client introuvable.", show_alert=True)
            return

        ok = await delivery_service.redeliver(
            callback.bot, session, order, user.telegram_id
        )
        await log_action(
            session, callback.from_user.id,
            "redeliver_manuel", f"order={order_id} ok={ok}"
        )

    msg = "✅ Re-livraison effectuée." if ok else "❌ Échec de re-livraison."
    await callback.answer(msg, show_alert=True)
