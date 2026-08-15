"""
Registre central de TOUS les messages texte du bot.

Principe identique à services/labels.py (boutons) mais pour les textes
longs : messages de bienvenue, livraison, rupture de stock, dépôt, etc.
Chaque message a une clé fixe, un texte par défaut, et peut être surchargé
par l'admin depuis le panel ⚙️ Paramètres → Messages.

Variables disponibles dans les templates (remplacées à l'affichage) :
  {shop_name}       → nom de la boutique (setting shop_name)
  {product_name}    → nom du produit acheté
  {amount}          → montant formaté (ex: 12.50$)
  {balance}         → solde formaté
  {currency}        → code crypto (ex: BTC)
  {address}         → adresse de paiement
  {pay_amount}      → quantité crypto à envoyer
  {support}         → @username support
  {content}         → contenu livré (texte)
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Setting

_KEY_PREFIX = "msg:"


@dataclass(frozen=True)
class MessageDef:
    key: str
    label: str
    default: str
    section: str
    variables: list[str]  # variables disponibles dans ce message


MESSAGES: list[MessageDef] = [
    # --- Accueil ---
    MessageDef(
        key="welcome",
        label="Message de bienvenue (/start)",
        default=(
            "👋 Bienvenue sur <b>{shop_name}</b> !\n\n"
            "Parcourez la boutique, rechargez votre solde et recevez vos produits "
            "automatiquement, sans jamais quitter Telegram."
        ),
        section="Accueil",
        variables=["{shop_name}"],
    ),
    MessageDef(
        key="maintenance",
        label="Message mode maintenance",
        default=(
            "🔧 <b>{shop_name}</b> est temporairement en maintenance.\n\n"
            "Revenez dans quelques instants, nous serons bientôt de retour !"
        ),
        section="Accueil",
        variables=["{shop_name}"],
    ),
    MessageDef(
        key="banned",
        label="Message compte banni",
        default=(
            "🚫 Votre compte a été suspendu.\n"
            "Contactez le support si vous pensez qu'il s'agit d'une erreur."
        ),
        section="Accueil",
        variables=[],
    ),

    # --- Boutique ---
    MessageDef(
        key="out_of_stock",
        label="Message rupture de stock",
        default="⚠️ Ce produit est actuellement en rupture de stock. Un restock arrive bientôt.",
        section="Boutique",
        variables=[],
    ),
    MessageDef(
        key="purchase_confirm",
        label="Message confirmation d'achat",
        default=(
            "Confirmez-vous l'achat de <b>{product_name}</b> pour {amount} ?\n\n"
            "Votre solde actuel : {balance}"
        ),
        section="Boutique",
        variables=["{product_name}", "{amount}", "{balance}"],
    ),
    MessageDef(
        key="purchase_success",
        label="Message après achat réussi",
        default="✅ Achat confirmé — <b>{product_name}</b> vous a été livré ci-dessus.",
        section="Boutique",
        variables=["{product_name}"],
    ),
    MessageDef(
        key="purchase_insufficient",
        label="Message solde insuffisant",
        default=(
            "❌ Solde insuffisant pour cet achat.\n"
            "Rechargez votre solde depuis la section Portefeuille."
        ),
        section="Boutique",
        variables=[],
    ),
    MessageDef(
        key="purchase_refunded",
        label="Message remboursement automatique",
        default=(
            "❌ Une erreur est survenue lors de la livraison.\n"
            "Vous avez été remboursé automatiquement ({amount}). Le support a été notifié."
        ),
        section="Boutique",
        variables=["{amount}"],
    ),

    # --- Livraison ---
    MessageDef(
        key="delivery_file",
        label="Légende livraison fichier",
        default="✅ Voici votre produit. Merci pour votre achat !",
        section="Livraison",
        variables=[],
    ),
    MessageDef(
        key="delivery_text",
        label="Message livraison texte",
        default="✅ Voici votre produit. Merci pour votre achat !\n\n{content}",
        section="Livraison",
        variables=["{content}"],
    ),

    # --- Portefeuille / dépôts ---
    MessageDef(
        key="deposit_instructions",
        label="Instructions paiement crypto",
        default=(
            "💳 <b>Paiement en attente</b>\n\n"
            "Montant à envoyer : <code>{pay_amount} {currency}</code>\n"
            "Adresse : <code>{address}</code>\n\n"
            "Votre solde sera crédité automatiquement dès confirmation du paiement "
            "sur le réseau. Vous recevrez une notification ici même."
        ),
        section="Portefeuille",
        variables=["{pay_amount}", "{currency}", "{address}"],
    ),
    MessageDef(
        key="deposit_confirmed",
        label="Message dépôt confirmé (client)",
        default=(
            "✅ Votre dépôt de {amount} a été confirmé.\n"
            "Nouveau solde : {balance}"
        ),
        section="Portefeuille",
        variables=["{amount}", "{balance}"],
    ),
    MessageDef(
        key="deposit_confirmed_admin",
        label="Notification dépôt confirmé (admin)",
        default="💰 Nouveau dépôt confirmé : {amount} de @{support}",
        section="Portefeuille",
        variables=["{amount}", "{support}"],
    ),

    # --- Support ---
    MessageDef(
        key="support_text",
        label="Message page support",
        default="Besoin d'aide ? Contactez notre support, on répond rapidement 🙂",
        section="Support",
        variables=[],
    ),

    # --- Admin notifications ---
    MessageDef(
        key="admin_low_stock",
        label="Alerte stock bas (admin)",
        default="⚠️ Stock bas : <b>{product_name}</b> — {amount} unité(s) restante(s).",
        section="Admin",
        variables=["{product_name}", "{amount}"],
    ),
    MessageDef(
        key="admin_new_client",
        label="Alerte nouveau client (admin)",
        default="👤 Nouveau client inscrit : @{support} (<code>{amount}</code>)",
        section="Admin",
        variables=["{support}", "{amount}"],
    ),
    MessageDef(
        key="admin_delivery_fail",
        label="Alerte échec livraison (admin)",
        default=(
            "⚠️ Erreur de livraison automatique.\n"
            "Commande #{amount} — Erreur : {content}"
        ),
        section="Admin",
        variables=["{amount}", "{content}"],
    ),
]

_BY_KEY: dict[str, MessageDef] = {m.key: m for m in MESSAGES}
SECTIONS: list[str] = list(dict.fromkeys(m.section for m in MESSAGES))


def get_definition(key: str) -> MessageDef | None:
    return _BY_KEY.get(key)


def messages_in_section(section: str) -> list[MessageDef]:
    return [m for m in MESSAGES if m.section == section]


async def get_message(session: AsyncSession, key: str, **kwargs) -> str:
    """
    Retourne le message effectif pour la clé donnée, avec les variables
    remplacées. Utilise la surcharge admin si elle existe, sinon le défaut.
    """
    definition = _BY_KEY.get(key)
    if not definition:
        return f"[message manquant: {key}]"

    db_key = f"{_KEY_PREFIX}{key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    row = result.scalar_one_or_none()
    template = row.value if row is not None else definition.default

    for var, val in kwargs.items():
        template = template.replace("{" + var + "}", str(val))
    return template


async def get_all_messages(session: AsyncSession) -> dict[str, str]:
    """Retourne toutes les surcharges actuelles (clé → valeur effective)."""
    result = await session.execute(
        select(Setting).where(Setting.key.startswith(_KEY_PREFIX))
    )
    overrides = {row.key[len(_KEY_PREFIX):]: row.value for row in result.scalars().all()}
    return {m.key: overrides.get(m.key, m.default) for m in MESSAGES}


async def set_message(session: AsyncSession, key: str, value: str) -> str:
    if key not in _BY_KEY:
        raise ValueError(f"Clé inconnue : {key}")
    value = value.strip()
    if not value:
        raise ValueError("Le message ne peut pas être vide.")

    db_key = f"{_KEY_PREFIX}{key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    row = result.scalar_one_or_none()
    if row is None:
        from db.models import Setting as SettingModel
        session.add(SettingModel(key=db_key, value=value))
    else:
        row.value = value
    await session.commit()
    return value


async def reset_message(session: AsyncSession, key: str) -> str:
    definition = _BY_KEY[key]
    db_key = f"{_KEY_PREFIX}{key}"
    result = await session.execute(select(Setting).where(Setting.key == db_key))
    row = result.scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.commit()
    return definition.default
