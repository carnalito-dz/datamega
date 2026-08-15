"""Claviers inline pour le panel admin."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, Product


def admin_main_menu_kb(labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=labels.get("admin_menu_dashboard", "📊 Dashboard"), callback_data="admin:dashboard")],
        [
            InlineKeyboardButton(text=labels.get("admin_menu_products", "📦 Produits"), callback_data="admin:products"),
            InlineKeyboardButton(text=labels.get("admin_menu_categories", "📂 Catégories"), callback_data="admin:categories"),
        ],
        [
            InlineKeyboardButton(text=labels.get("admin_menu_stock", "📥 Stock"), callback_data="admin:stock"),
            InlineKeyboardButton(text=labels.get("admin_menu_clients", "👥 Clients"), callback_data="admin:clients"),
        ],
        [
            InlineKeyboardButton(text=labels.get("admin_menu_wallet", "💰 Portefeuille"), callback_data="admin:wallet"),
            InlineKeyboardButton(text=labels.get("admin_menu_orders", "🧾 Commandes"), callback_data="admin:orders"),
        ],
        [
            InlineKeyboardButton(text=labels.get("admin_menu_stats", "📈 Statistiques"), callback_data="admin:stats"),
            InlineKeyboardButton(text=labels.get("admin_menu_notifications", "🔔 Notifications"), callback_data="admin:notifications"),
        ],
        [
            InlineKeyboardButton(text="💬 Messagerie", callback_data="admin:messaging"),
            InlineKeyboardButton(text="🎟 Codes promo", callback_data="admin:promo"),
        ],
        [
            InlineKeyboardButton(text="📣 Broadcast", callback_data="admin:broadcast"),
            InlineKeyboardButton(text=labels.get("admin_menu_logs", "📜 Journal"), callback_data="admin:logs"),
        ],
        [
            InlineKeyboardButton(text=labels.get("admin_menu_settings", "⚙️ Paramètres"), callback_data="admin:settings"),
            InlineKeyboardButton(text=labels.get("admin_menu_labels", "🏷 Libellés"), callback_data="admin:labels"),
        ],
    ])


def back_to_admin_kb(labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("admin_back_home", "⬅️ Menu admin"),
            callback_data="admin:home",
        )]
    ])


# ── Catégories ────────────────────────────────────────────────────────────────

def categories_admin_kb(categories: list[Category], labels: dict) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        status = "✅" if cat.is_active else "🚫"
        rows.append([InlineKeyboardButton(
            text=f"{status} {cat.name}",
            callback_data=f"admin:cat:view:{cat.id}",
        )])
    rows.append([InlineKeyboardButton(text=labels.get("admin_cat_add", "➕ Ajouter catégorie"), callback_data="admin:cat:add")])
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_detail_kb(cat: Category, labels: dict) -> InlineKeyboardMarkup:
    toggle = labels.get("admin_cat_disable", "🗑 Désactiver") if cat.is_active \
        else labels.get("admin_cat_enable", "🔄 Réactiver")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=labels.get("admin_cat_rename", "✏️ Renommer"), callback_data=f"admin:cat:rename:{cat.id}")],
        [InlineKeyboardButton(text=toggle, callback_data=f"admin:cat:toggle:{cat.id}")],
        [
            InlineKeyboardButton(text=labels.get("admin_cat_up", "⬆️ Monter"), callback_data=f"admin:cat:up:{cat.id}"),
            InlineKeyboardButton(text=labels.get("admin_cat_down", "⬇️ Descendre"), callback_data=f"admin:cat:down:{cat.id}"),
        ],
        [InlineKeyboardButton(text=labels.get("admin_cat_back", "⬅️ Catégories"), callback_data="admin:categories")],
    ])


# ── Produits ──────────────────────────────────────────────────────────────────

def products_admin_kb(products: list[Product], labels: dict) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        icon = {"draft": "📝", "published": "✅", "deleted": "🗑"}.get(p.status.value, "")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {p.name}",
            callback_data=f"admin:prod:view:{p.id}",
        )])
    rows.append([InlineKeyboardButton(text=labels.get("admin_prod_add", "➕ Ajouter produit"), callback_data="admin:prod:add")])
    rows.append([InlineKeyboardButton(text=labels.get("admin_prod_search", "🔎 Rechercher"), callback_data="admin:prod:search")])
    rows.append([InlineKeyboardButton(text=labels.get("admin_prod_trash", "🗑 Corbeille"), callback_data="admin:prod:trash")])
    rows.append([InlineKeyboardButton(text="📥 Import mots-clés (CSV)", callback_data="admin:keywords:import")])
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_admin_kb(p: Product, labels: dict) -> InlineKeyboardMarkup:
    pub_text = labels.get("admin_prod_unpublish", "🚫 Repasser en brouillon") \
        if p.status.value == "published" \
        else labels.get("admin_prod_publish", "✅ Publier")
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=labels.get("admin_prod_edit_name", "✏️ Nom"), callback_data=f"admin:prod:edit:name:{p.id}"),
            InlineKeyboardButton(text=labels.get("admin_prod_edit_description", "✏️ Description"), callback_data=f"admin:prod:edit:description:{p.id}"),
        ],
        [
            InlineKeyboardButton(text=labels.get("admin_prod_edit_price", "✏️ Prix"), callback_data=f"admin:prod:edit:price:{p.id}"),
            InlineKeyboardButton(text=labels.get("admin_prod_edit_image", "🖼 Image"), callback_data=f"admin:prod:edit:image:{p.id}"),
        ],
        [InlineKeyboardButton(text=labels.get("admin_prod_restock", "📥 Restock"), callback_data=f"admin:prod:restock:{p.id}")],
        [InlineKeyboardButton(text="🔑 Mots-clés", callback_data=f"admin:prod:keywords:{p.id}")],
        [InlineKeyboardButton(text=pub_text, callback_data=f"admin:prod:togglepub:{p.id}")],
        [InlineKeyboardButton(text=labels.get("admin_prod_delete", "🗑 Supprimer"), callback_data=f"admin:prod:delete:{p.id}")],
        [InlineKeyboardButton(text=labels.get("admin_prod_back", "⬅️ Produits"), callback_data="admin:products")],
    ])


def trash_kb(products: list[Product], labels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{labels.get('admin_prod_restore_prefix', '♻️ Restaurer')} {p.name}",
            callback_data=f"admin:prod:restore:{p.id}",
        )]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_search_results_kb(products: list[Product], labels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=p.name, callback_data=f"admin:prod:view:{p.id}")]
        for p in products
    ]
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Utilitaires ───────────────────────────────────────────────────────────────

def category_picker_kb(categories: list[Category], prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cat.name, callback_data=f"{prefix}:{cat.id}")]
        for cat in categories
    ])


def skip_kb(callback_data: str, labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("common_skip", "⏭ Passer"),
            callback_data=callback_data,
        )]
    ])


def finish_files_kb(callback_data: str, labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("common_finish_upload", "✅ Terminer l'envoi"),
            callback_data=callback_data,
        )]
    ])


# ── Settings ──────────────────────────────────────────────────────────────────

def settings_list_kb(keys: list[str], labels: dict) -> InlineKeyboardMarkup:
    from services.settings import get_definition
    rows = [
        [InlineKeyboardButton(
            text=f"✏️ {get_definition(k).label if get_definition(k) else k}",
            callback_data=f"admin:setting:edit:{k}",
        )]
        for k in keys
    ]
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def setting_detail_kb(key: str, labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("admin_setting_back", "⬅️ Réglages"),
            callback_data="admin:settings:general",
        )]
    ])


# ── Labels ────────────────────────────────────────────────────────────────────

def labels_sections_kb(sections: list[str], labels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=sec, callback_data=f"admin:label:section:{i}")]
        for i, sec in enumerate(sections)
    ]
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def labels_in_section_kb(section_idx: int, keys: list[str], labels: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"✏️ {labels.get(key, key)[:30]}",
            callback_data=f"admin:label:edit:{key}",
        )]
        for key in keys
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Sections", callback_data="admin:labels")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def label_detail_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Réinitialiser", callback_data=f"admin:label:reset:{key}")],
        [InlineKeyboardButton(text="⬅️ Annuler", callback_data="admin:labels")],
    ])


# ── Wallet admin ──────────────────────────────────────────────────────────────

def client_detail_kb(telegram_id: int, labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=labels.get("admin_client_credit", "➕ Créditer"), callback_data=f"admin:client:credit:{telegram_id}"),
            InlineKeyboardButton(text=labels.get("admin_client_debit", "➖ Débiter"), callback_data=f"admin:client:debit:{telegram_id}"),
        ],
        [InlineKeyboardButton(text=labels.get("admin_client_back", "⬅️ Clients"), callback_data="admin:clients")],
    ])
