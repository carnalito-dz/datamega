"""
Registre central de TOUS les libellés de boutons du bot (client + admin),
modifiables depuis Telegram sans toucher au code ni redéployer.

Fonctionnement : chaque bouton du bot a une clé fixe (ex: "shop_buy") avec
un texte par défaut (ex: "🛒 Acheter"). La valeur effective vient de la
table `settings` (clé préfixée "label:") si l'admin l'a modifiée, sinon du
défaut ci-dessous. C'est le même principe que services/settings.py, mais
dans une table de registre séparée car il y a ~40 entrées, organisées par
section pour rester navigable dans le panel admin (handlers/admin/labels.py).

Pour ajouter un nouveau bouton au bot : ajouter une entrée ici, puis
utiliser labels[\"ma_cle\"] dans la fonction de clavier concernée au lieu
d'un texte en dur.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Setting

_KEY_PREFIX = "label:"


@dataclass(frozen=True)
class LabelDef:
    key: str
    default: str
    section: str


# --------------------------------------------------------------------------- #
# Registre : (clé, texte par défaut, section pour l'affichage dans le panel)
# --------------------------------------------------------------------------- #
LABELS: list[LabelDef] = [
    # --- Menu principal client (clavier persistant en bas de l'écran) ---
    LabelDef("menu_shop", "🏪 Boutique", "Menu client"),
    LabelDef("menu_wallet", "💰 Mon Solde", "Menu client"),
    LabelDef("menu_purchases", "🛒 Mes Achats", "Menu client"),
    LabelDef("menu_account", "👤 Mon Compte", "Menu client"),
    LabelDef("menu_support", "📞 Support", "Menu client"),

    # --- Boutique ---
    LabelDef("shop_back_to_categories", "⬅️ Retour aux catégories", "Boutique"),
    LabelDef("shop_buy", "🛒 Acheter", "Boutique"),
    LabelDef("shop_back", "⬅️ Retour", "Boutique"),
    LabelDef("shop_confirm", "✅ Confirmer l'achat", "Boutique"),
    LabelDef("shop_cancel", "❌ Annuler", "Boutique"),

    # --- Portefeuille / dépôts ---
    LabelDef("wallet_deposit", "➕ Recharger mon solde", "Portefeuille"),
    LabelDef("wallet_history", "📜 Historique", "Portefeuille"),
    LabelDef("deposit_custom", "✏️ Autre montant", "Portefeuille"),

    # --- Support ---
    LabelDef("support_contact", "✉️ Contacter le support", "Support"),

    # --- Menu principal admin ---
    LabelDef("admin_menu_dashboard", "📊 Dashboard", "Menu admin"),
    LabelDef("admin_menu_products", "📦 Produits", "Menu admin"),
    LabelDef("admin_menu_categories", "📂 Catégories", "Menu admin"),
    LabelDef("admin_menu_stock", "📥 Stock", "Menu admin"),
    LabelDef("admin_menu_clients", "👥 Clients", "Menu admin"),
    LabelDef("admin_menu_wallet", "💰 Portefeuille", "Menu admin"),
    LabelDef("admin_menu_orders", "🧾 Commandes", "Menu admin"),
    LabelDef("admin_menu_stats", "📈 Statistiques", "Menu admin"),
    LabelDef("admin_menu_notifications", "🔔 Notifications", "Menu admin"),
    LabelDef("admin_menu_logs", "📜 Journal", "Menu admin"),
    LabelDef("admin_menu_settings", "⚙️ Paramètres", "Menu admin"),
    LabelDef("admin_menu_labels", "🏷 Libellés", "Menu admin"),
    LabelDef("admin_back_home", "⬅️ Menu admin", "Menu admin"),

    # --- Catégories (admin) ---
    LabelDef("admin_cat_add", "➕ Ajouter catégorie", "Catégories (admin)"),
    LabelDef("admin_cat_rename", "✏️ Renommer", "Catégories (admin)"),
    LabelDef("admin_cat_disable", "🗑 Désactiver", "Catégories (admin)"),
    LabelDef("admin_cat_enable", "🔄 Réactiver", "Catégories (admin)"),
    LabelDef("admin_cat_up", "⬆️ Monter", "Catégories (admin)"),
    LabelDef("admin_cat_down", "⬇️ Descendre", "Catégories (admin)"),
    LabelDef("admin_cat_back", "⬅️ Catégories", "Catégories (admin)"),

    # --- Produits (admin) ---
    LabelDef("admin_prod_add", "➕ Ajouter produit", "Produits (admin)"),
    LabelDef("admin_prod_search", "🔎 Rechercher", "Produits (admin)"),
    LabelDef("admin_prod_trash", "🗑 Corbeille", "Produits (admin)"),
    LabelDef("admin_prod_edit_name", "✏️ Nom", "Produits (admin)"),
    LabelDef("admin_prod_edit_description", "✏️ Description", "Produits (admin)"),
    LabelDef("admin_prod_edit_price", "✏️ Prix", "Produits (admin)"),
    LabelDef("admin_prod_edit_image", "🖼 Image", "Produits (admin)"),
    LabelDef("admin_prod_restock", "📥 Restock", "Produits (admin)"),
    LabelDef("admin_prod_unpublish", "🚫 Repasser en brouillon", "Produits (admin)"),
    LabelDef("admin_prod_publish", "✅ Publier", "Produits (admin)"),
    LabelDef("admin_prod_delete", "🗑 Supprimer", "Produits (admin)"),
    LabelDef("admin_prod_back", "⬅️ Produits", "Produits (admin)"),
    LabelDef("admin_prod_restore_prefix", "♻️ Restaurer", "Produits (admin)"),
    LabelDef("common_skip", "⏭ Passer", "Produits (admin)"),
    LabelDef("common_finish_upload", "✅ Terminer l'envoi", "Produits (admin)"),

    # --- Clients (admin) ---
    LabelDef("admin_client_credit", "➕ Créditer", "Clients (admin)"),
    LabelDef("admin_client_debit", "➖ Débiter", "Clients (admin)"),
    LabelDef("admin_client_back", "⬅️ Clients", "Clients (admin)"),

    # --- Réglages (admin) ---
    LabelDef("admin_setting_edit", "✏️ Modifier", "Réglages (admin)"),
    LabelDef("admin_setting_back", "⬅️ Réglages", "Réglages (admin)"),
]

_BY_KEY: dict[str, LabelDef] = {lb.key: lb for lb in LABELS}
SECTIONS: list[str] = list(dict.fromkeys(lb.section for lb in LABELS))  # ordre stable, sans doublons


def get_definition(key: str) -> LabelDef | None:
    return _BY_KEY.get(key)


def labels_in_section(section: str) -> list[LabelDef]:
    return [lb for lb in LABELS if lb.section == section]


async def get_labels(session: AsyncSession) -> dict[str, str]:
    """
    Retourne le dict COMPLET {clé: texte effectif} pour tous les boutons
    du bot, en une seule requête. À appeler une fois par update (voir la
    middleware dans main.py) plutôt qu'une fois par bouton.
    """
    result = await session.execute(
        select(Setting).where(Setting.key.startswith(_KEY_PREFIX))
    )
    overrides = {row.key[len(_KEY_PREFIX):]: row.value for row in result.scalars().all()}
    return {lb.key: overrides.get(lb.key, lb.default) for lb in LABELS}


async def set_label(session: AsyncSession, key: str, value: str) -> str:
    definition = _BY_KEY[key]
    normalized = value.strip()
    if not normalized:
        raise ValueError("Le libellé ne peut pas être vide.")

    db_key = f"{_KEY_PREFIX}{key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    row = result.scalar_one_or_none()
    if row is None:
        session.add(Setting(key=db_key, value=normalized))
    else:
        row.value = normalized
    await session.commit()
    return normalized


async def reset_label(session: AsyncSession, key: str) -> str:
    """Supprime la surcharge et revient au texte par défaut."""
    definition = _BY_KEY[key]
    db_key = f"{_KEY_PREFIX}{key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    row = result.scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return definition.default
