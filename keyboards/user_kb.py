"""Claviers reply et inline pour les clients."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup,
)

import config
from db.models import Category, Product


def main_menu_kb(labels: dict) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=labels.get("menu_shop", "🛍 Boutique")),
                KeyboardButton(text=labels.get("menu_wallet", "💳 Portefeuille")),
            ],
            [
                KeyboardButton(text=labels.get("menu_purchases", "🛒 Mes achats")),
                KeyboardButton(text=labels.get("menu_account", "👤 Mon compte")),
            ],
            [
                KeyboardButton(text=labels.get("menu_support", "💬 Support")),
            ],
        ],
        resize_keyboard=True,
    )


def categories_kb(categories: list[Category]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{cat.emoji or ''} {cat.name}",
            callback_data=f"shop:cat:{cat.id}",
        )]
        for cat in categories
    ]
    rows.append([InlineKeyboardButton(
        text="🔎 Rechercher un article",
        callback_data="shop:search",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_kb(products: list[Product], category_id: int,
                labels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=product.name,
            callback_data=f"shop:product:{product.id}",
        )]
        for product in products
    ]
    rows.append([InlineKeyboardButton(
        text=labels.get("shop_back_categories", "⬅️ Catégories"),
        callback_data="shop:categories",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(product_id: int, in_stock: bool,
                      labels: dict) -> InlineKeyboardMarkup:
    rows = []
    if in_stock:
        rows.append([InlineKeyboardButton(
            text=labels.get("shop_buy_btn", "🛒 Acheter"),
            callback_data=f"shop:buy:{product_id}",
        )])
    rows.append([InlineKeyboardButton(
        text=labels.get("shop_back_products", "⬅️ Retour"),
        callback_data="shop:back_to_products",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quantity_kb(max_qty: int, product_id: int) -> InlineKeyboardMarkup:
    """Clavier de sélection de quantité (1 à max_qty)."""
    row = []
    rows = []
    for i in range(1, max_qty + 1):
        row.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"shop:qty:{i}:{product_id}",
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Annuler", callback_data="shop:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_purchase_kb(product_id: int, labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("shop_confirm_btn", "✅ Confirmer"),
            callback_data=f"shop:confirm:{product_id}",
        )],
        [InlineKeyboardButton(
            text=labels.get("shop_cancel_btn", "❌ Annuler"),
            callback_data="shop:cancel",
        )],
    ])


def search_result_kb(results: list[tuple], labels: dict) -> InlineKeyboardMarkup:
    """results : [(product, count_available), ...]"""
    rows = [
        [InlineKeyboardButton(
            text=f"🛒 {prod.name} ({count} dispo)",
            callback_data=f"shop:product:{prod.id}",
        )]
        for prod, count in results
    ]
    rows.append([InlineKeyboardButton(
        text=labels.get("shop_back_categories", "⬅️ Catégories"),
        callback_data="shop:categories",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deposit_amount_kb(presets: list[int], labels: dict) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for amount in presets:
        row.append(InlineKeyboardButton(
            text=f"{amount}$",
            callback_data=f"deposit:amount:{amount * 100}",
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text=labels.get("deposit_custom", "✍️ Montant personnalisé"),
        callback_data="deposit:custom",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def deposit_currency_kb(enabled_cryptos: dict[str, str] | None = None) -> InlineKeyboardMarkup:
    cryptos = enabled_cryptos if enabled_cryptos is not None else config.DEPOSIT_CURRENCIES
    rows = [
        [InlineKeyboardButton(
            text=label,
            callback_data=f"deposit:currency:{code}",
        )]
        for code, label in cryptos.items()
    ]
    if not rows:
        rows = [[InlineKeyboardButton(
            text="Aucun mode de paiement disponible",
            callback_data="noop",
        )]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_kb(support_username: str, labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("support_contact", "✉️ Contacter le support"),
            url=f"https://t.me/{support_username.lstrip('@')}",
        )],
        [InlineKeyboardButton(
            text="💬 Envoyer un message",
            callback_data="support:write",
        )],
        [InlineKeyboardButton(
            text="📜 Voir mes messages",
            callback_data="support:history",
        )],
    ])
