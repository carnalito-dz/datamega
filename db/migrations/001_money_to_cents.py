"""
Migration 001 : montants USD `float` -> centimes entiers (`int`).

Contexte : les colonnes monétaires (soldes, prix, montants de transaction)
étaient stockées en `Float`, ce qui expose à des erreurs d'arrondi binaire
cumulées sur les soldes. Elles passent à un entier représentant des
centimes, exact aussi bien sur SQLite que sur PostgreSQL. Voir
utils/money.py pour les fonctions de conversion utilisées partout ailleurs
dans le code.

Garanties :
  - IDEMPOTENTE : peut être relancée sans risque, elle détecte l'état déjà
    migré et ne refait rien.
  - NON DESTRUCTIVE : les anciennes colonnes float ne sont jamais
    supprimées, seulement renommées avec le suffixe `_deprecated_float`.
    Elles restent consultables pour vérification manuelle ; leur
    suppression définitive doit faire l'objet d'une migration ultérieure
    séparée, une fois les nouveaux montants validés en production.
  - Conversion précise : on reconstruit le nombre décimal à partir de
    `str(valeur_float)` (la représentation la plus courte qui redonne
    exactement ce float), puis on multiplie par 100 en Decimal — pas de
    multiplication flottante directe qui réintroduirait le biais qu'on
    cherche justement à éliminer.

Usage (à exécuter une fois, AVANT de démarrer le bot avec le nouveau code,
sur une base de données existante créée par une version antérieure) :

    cd datamega_v2
    python -m db.migrations.001_money_to_cents

Sur une base flambant neuve (jamais démarrée), cette migration n'a rien à
faire : `init_db()` crée directement les tables avec les colonnes `_cents`.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import inspect, text

from db.session import engine

# (table, colonne_float_source, nouvelle_colonne_cents)
MONEY_COLUMNS = [
    ("wallets", "balance", "balance_cents"),
    ("wallet_transactions", "amount", "amount_cents"),
    ("wallet_transactions", "balance_after", "balance_after_cents"),
    ("products", "price", "price_cents"),
    ("orders", "price", "price_cents"),
    ("deposits", "amount_usd", "amount_usd_cents"),
]

DEPRECATED_SUFFIX = "_deprecated_float"


def _float_to_cents(value) -> int:
    if value is None:
        return 0
    return int((Decimal(str(value)) * 100).to_integral_value())


async def _table_columns(conn, table: str) -> set[str]:
    def _reflect(sync_conn):
        return {col["name"] for col in inspect(sync_conn).get_columns(table)}
    return await conn.run_sync(_reflect)


async def _migrate_money_column(conn, table: str, old_col: str, new_col: str) -> None:
    cols = await _table_columns(conn, table)

    if new_col in cols and old_col not in cols:
        print(f"[skip]    {table}.{new_col} déjà en place — déjà migré.")
        return

    if new_col not in cols:
        print(f"[migrate] {table}: ajout de la colonne {new_col}")
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {new_col} INTEGER"))

    if old_col in cols:
        rows = (await conn.execute(text(f"SELECT id, {old_col} FROM {table}"))).all()
        print(f"[migrate] {table}: conversion de {len(rows)} ligne(s) {old_col} -> {new_col}")
        for row_id, value in rows:
            cents = _float_to_cents(value)
            await conn.execute(
                text(f"UPDATE {table} SET {new_col} = :cents WHERE id = :id"),
                {"cents": cents, "id": row_id},
            )
        deprecated_name = f"{old_col}{DEPRECATED_SUFFIX}"
        print(f"[migrate] {table}: renommage {old_col} -> {deprecated_name} (conservée, non supprimée)")
        await conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN {old_col} TO {deprecated_name}"))


async def _migrate_deposit_pay_amount(conn) -> None:
    """
    deposits.pay_amount passe de float (quantité crypto) à texte, puisque
    ce champ n'est jamais utilisé dans un calcul côté bot (uniquement
    affiché au client) : le stocker en texte évite toute perte de
    précision, y compris pour des cryptos à 8 décimales.

    Sur SQLite, le typage de colonne n'est qu'indicatif (affinité) : aucune
    action de conversion de type n'est nécessaire, les valeurs existantes
    restent lisibles telles quelles. Sur PostgreSQL, le type est appliqué
    strictement : on convertit explicitement la colonne si elle est encore
    numérique.
    """
    if conn.dialect.name != "postgresql":
        return

    def _col_type(sync_conn) -> str | None:
        for col in inspect(sync_conn).get_columns("deposits"):
            if col["name"] == "pay_amount":
                return str(col["type"])
        return None

    col_type = await conn.run_sync(_col_type)
    if col_type is None:
        return
    if "CHAR" in col_type.upper() or "TEXT" in col_type.upper():
        print("[skip]    deposits.pay_amount déjà en texte — déjà migré.")
        return

    print(f"[migrate] deposits.pay_amount: conversion {col_type} -> VARCHAR(64)")
    await conn.execute(
        text("ALTER TABLE deposits ALTER COLUMN pay_amount TYPE VARCHAR(64) USING pay_amount::text")
    )


async def migrate() -> None:
    async with engine.begin() as conn:
        for table, old_col, new_col in MONEY_COLUMNS:
            await _migrate_money_column(conn, table, old_col, new_col)
        await _migrate_deposit_pay_amount(conn)

    print(
        "\nMigration terminée. Les anciennes colonnes float ont été renommées "
        f"avec le suffixe '{DEPRECATED_SUFFIX}' et conservées pour vérification "
        "manuelle (aucune donnée supprimée). Une fois les nouveaux montants "
        "validés en production, une migration ultérieure pourra les supprimer "
        "définitivement."
    )


if __name__ == "__main__":
    asyncio.run(migrate())
