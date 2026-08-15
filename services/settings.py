"""
Réglages généraux modifiables depuis le panel admin.
Version étendue : nom boutique, monnaie, cryptos, solde bienvenue,
mode maintenance, modes de paiement, admins dynamiques, réinitialisation.

Secrets exclus (BOT_TOKEN, DATABASE_URL, clés NOWPayments) — voir v1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db.models import Setting
from utils.money import InvalidAmount, parse_usd_to_cents


class InvalidSettingValue(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Parseurs
# --------------------------------------------------------------------------- #

def _parse_str(raw: str) -> str:
    v = raw.strip()
    if not v:
        raise InvalidSettingValue("Valeur vide.")
    return v


def _parse_positive_int(raw: str) -> str:
    v = raw.strip()
    if not v.isdigit() or int(v) <= 0:
        raise InvalidSettingValue("Doit être un entier positif.")
    return v


def _parse_non_negative_int(raw: str) -> str:
    v = raw.strip()
    if not v.isdigit():
        raise InvalidSettingValue("Doit être un entier >= 0.")
    return v


def _parse_usd_amount(raw: str) -> str:
    try:
        cents = parse_usd_to_cents(raw)
    except InvalidAmount as exc:
        raise InvalidSettingValue(str(exc)) from exc
    return f"{cents / 100:.2f}"


def _parse_int_list(raw: str) -> str:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise InvalidSettingValue("Liste vide.")
    for p in parts:
        if not p.isdigit() or int(p) <= 0:
            raise InvalidSettingValue(
                "Chaque montant doit être un entier positif séparé par des virgules (ex: 10,20,50,100)."
            )
    return ",".join(parts)


def _parse_bool(raw: str) -> str:
    v = raw.strip().lower()
    if v in ("1", "oui", "on", "true", "yes", "actif", "activer"):
        return "1"
    if v in ("0", "non", "off", "false", "no", "inactif", "désactiver", "desactiver"):
        return "0"
    raise InvalidSettingValue("Répondez oui ou non (ou 1/0).")


def _parse_crypto_list(raw: str) -> str:
    """
    Liste de codes crypto séparés par virgule.
    Codes valides : sous-ensemble de DEPOSIT_CURRENCIES dans config.py.
    """
    valid = set(config.DEPOSIT_CURRENCIES.keys())
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if not parts:
        raise InvalidSettingValue("Liste vide.")
    unknown = [p for p in parts if p not in valid]
    if unknown:
        raise InvalidSettingValue(
            f"Codes inconnus : {', '.join(unknown)}. "
            f"Valides : {', '.join(sorted(valid))}"
        )
    return ",".join(parts)


def _parse_currency_symbol(raw: str) -> str:
    v = raw.strip()
    if not v or len(v) > 5:
        raise InvalidSettingValue("Symbole trop long (max 5 caractères).")
    return v


# --------------------------------------------------------------------------- #
# Registre des réglages
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SettingDef:
    key: str
    label: str
    help_text: str
    default: Callable[[], str]
    parse: Callable[[str], str]
    section: str


SETTINGS: list[SettingDef] = [
    # --- Identité ---
    SettingDef(
        key="shop_name",
        label="Nom de la boutique",
        help_text="Affiché dans les messages de bienvenue et partout où {shop_name} est utilisé.",
        default=lambda: "DATA MEGA",
        parse=_parse_str,
        section="Identité",
    ),
    SettingDef(
        key="currency_symbol",
        label="Symbole monétaire",
        help_text="Symbole affiché après les montants (ex: $, €, £). Max 5 caractères.",
        default=lambda: config.CURRENCY_SYMBOL,
        parse=_parse_currency_symbol,
        section="Identité",
    ),

    # --- Boutique ---
    SettingDef(
        key="maintenance_mode",
        label="Mode maintenance",
        help_text="Activé (oui/1) : la boutique est fermée, les clients voient le message maintenance. Désactivé (non/0) : fonctionnement normal.",
        default=lambda: "0",
        parse=_parse_bool,
        section="Boutique",
    ),
    SettingDef(
        key="welcome_bonus_cents",
        label="Solde offert aux nouveaux inscrits (centimes USD)",
        help_text="Montant crédité automatiquement à chaque nouveau client. 0 = désactivé. Ex: 500 = 5.00$.",
        default=lambda: "0",
        parse=_parse_non_negative_int,
        section="Boutique",
    ),
    SettingDef(
        key="low_stock_threshold",
        label="Seuil stock bas",
        help_text="En dessous de ce nombre d'unités disponibles, le produit est signalé ⚠️ dans le panel admin.",
        default=lambda: str(config.LOW_STOCK_THRESHOLD),
        parse=_parse_positive_int,
        section="Boutique",
    ),

    # --- Dépôts ---
    SettingDef(
        key="support_username",
        label="Nom d'utilisateur du support",
        help_text="Le @ du compte Telegram affiché au client (ex: @mon_support).",
        default=lambda: config.SUPPORT_USERNAME,
        parse=_parse_str,
        section="Dépôts",
    ),
    SettingDef(
        key="min_deposit_usd",
        label="Dépôt minimum (USD)",
        help_text="Montant minimum autorisé pour un rechargement libre (ex: 5).",
        default=lambda: str(config.MIN_DEPOSIT_USD),
        parse=_parse_usd_amount,
        section="Dépôts",
    ),
    SettingDef(
        key="deposit_presets",
        label="Montants de dépôt proposés (USD)",
        help_text="Liste séparée par virgules proposée en boutons rapides (ex: 10,20,50,100).",
        default=lambda: ",".join(str(v) for v in config.DEPOSIT_PRESETS),
        parse=_parse_int_list,
        section="Dépôts",
    ),
    SettingDef(
        key="enabled_cryptos",
        label="Cryptos acceptées",
        help_text=(
            "Codes séparés par virgules parmi : "
            + ", ".join(sorted(config.DEPOSIT_CURRENCIES.keys()))
            + ". Ex: btc,eth,usdttrc20"
        ),
        default=lambda: ",".join(config.DEPOSIT_CURRENCIES.keys()),
        parse=_parse_crypto_list,
        section="Dépôts",
    ),
    SettingDef(
        key="nowpayments_enabled",
        label="Paiement NOWPayments activé",
        help_text="Désactivez pour bloquer tous les dépôts crypto sans supprimer la configuration.",
        default=lambda: "1",
        parse=_parse_bool,
        section="Dépôts",
    ),
]

_BY_KEY: dict[str, SettingDef] = {s.key: s for s in SETTINGS}
SECTIONS: list[str] = list(dict.fromkeys(s.section for s in SETTINGS))


def get_definition(key: str) -> SettingDef | None:
    return _BY_KEY.get(key)


def settings_in_section(section: str) -> list[SettingDef]:
    return [s for s in SETTINGS if s.section == section]


async def get_raw(session: AsyncSession, key: str) -> str:
    definition = _BY_KEY[key]
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row is not None else definition.default()


async def get_all_raw(session: AsyncSession) -> dict[str, str]:
    return {s.key: await get_raw(session, s.key) for s in SETTINGS}


async def set_value(session: AsyncSession, key: str, raw_value: str) -> str:
    definition = _BY_KEY[key]
    normalized = definition.parse(raw_value)
    result = await session.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        session.add(Setting(key=key, value=normalized))
    else:
        row.value = normalized
    await session.commit()
    return normalized


# --- Accesseurs typés ---

async def get_shop_name(session: AsyncSession) -> str:
    return await get_raw(session, "shop_name")

async def get_currency_symbol(session: AsyncSession) -> str:
    return await get_raw(session, "currency_symbol")

async def get_support_username(session: AsyncSession) -> str:
    return await get_raw(session, "support_username")

async def get_min_deposit_usd(session: AsyncSession) -> float:
    return float(await get_raw(session, "min_deposit_usd"))

async def get_low_stock_threshold(session: AsyncSession) -> int:
    return int(await get_raw(session, "low_stock_threshold"))

async def get_deposit_presets(session: AsyncSession) -> list[int]:
    raw = await get_raw(session, "deposit_presets")
    return [int(p) for p in raw.split(",") if p.strip()]

async def get_enabled_cryptos(session: AsyncSession) -> dict[str, str]:
    raw = await get_raw(session, "enabled_cryptos")
    enabled = {p.strip() for p in raw.split(",") if p.strip()}
    return {k: v for k, v in config.DEPOSIT_CURRENCIES.items() if k in enabled}

async def is_maintenance(session: AsyncSession) -> bool:
    return await get_raw(session, "maintenance_mode") == "1"

async def is_nowpayments_enabled(session: AsyncSession) -> bool:
    return await get_raw(session, "nowpayments_enabled") == "1"

async def get_welcome_bonus_cents(session: AsyncSession) -> int:
    return int(await get_raw(session, "welcome_bonus_cents"))


# --------------------------------------------------------------------------- #
# Admins dynamiques
# --------------------------------------------------------------------------- #

_ADMIN_LIST_KEY = "dynamic_admin_ids"


async def get_dynamic_admin_ids(session: AsyncSession) -> set[int]:
    """IDs admin ajoutés depuis le panel (en plus de ADMIN_IDS dans config.py)."""
    result = await session.execute(select(Setting).where(Setting.key == _ADMIN_LIST_KEY))
    row = result.scalar_one_or_none()
    if not row or not row.value.strip():
        return set()
    return {int(x) for x in row.value.split(",") if x.strip().isdigit()}


async def get_all_admin_ids(session: AsyncSession) -> set[int]:
    """Tous les admins : config.py + panel."""
    dynamic = await get_dynamic_admin_ids(session)
    return config.ADMIN_IDS | dynamic


async def add_admin(session: AsyncSession, telegram_id: int) -> None:
    ids = await get_dynamic_admin_ids(session)
    ids.add(telegram_id)
    await _save_admin_ids(session, ids)


async def remove_admin(session: AsyncSession, telegram_id: int) -> bool:
    """Retourne False si l'ID était dans config.py (non supprimable)."""
    if telegram_id in config.ADMIN_IDS:
        return False
    ids = await get_dynamic_admin_ids(session)
    ids.discard(telegram_id)
    await _save_admin_ids(session, ids)
    return True


async def _save_admin_ids(session: AsyncSession, ids: set[int]) -> None:
    value = ",".join(str(i) for i in sorted(ids))
    result = await session.execute(select(Setting).where(Setting.key == _ADMIN_LIST_KEY))
    row = result.scalar_one_or_none()
    if row is None:
        session.add(Setting(key=_ADMIN_LIST_KEY, value=value))
    else:
        row.value = value
    await session.commit()


# --------------------------------------------------------------------------- #
# Réinitialisation complète
# --------------------------------------------------------------------------- #

async def factory_reset(session: AsyncSession) -> None:
    """
    Remet le bot à zéro : supprime TOUTES les données sauf les tables
    structurelles. Irréversible.
    Tables vidées : users, wallets, wallet_transactions, categories,
    products, product_stock, orders, deposits, admin_logs, notifications,
    settings.
    """
    from sqlalchemy import text
    # Ordre critique : enfants avant parents (FK constraints)
    # SQLite accepte les DELETE dans le mauvais ordre SAUF si foreign_keys est ON
    # On préfère respecter l'ordre correct dans tous les cas.
    tables = [
        "wallet_transactions",  # FK -> wallets, users
        "promo_uses",           # FK -> promo_codes, users, orders
        "deposits",             # FK -> users
        "orders",               # FK -> users, products, product_stock
        "promo_codes",          # aucune FK enfant ici
        "support_messages",     # FK -> users
        "product_keywords",     # FK -> products  ← AVANT products
        "product_stock",        # FK -> products  ← AVANT products
        "products",             # FK -> categories
        "categories",
        "notifications",
        "admin_logs",
        "wallets",              # FK -> users     ← AVANT users
        "users",
        "settings",
    ]
    for table in tables:
        await session.execute(text(f"DELETE FROM {table}"))
    await session.commit()
