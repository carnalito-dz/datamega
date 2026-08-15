"""
Migration 002 : unités de stock en texte, en plus des fichiers.

Ajoute product_stock.text_content (nullable). N'exige AUCUN changement de
contrainte sur telegram_file_id (qui reste NOT NULL en base) : une unité
"texte" y stocke simplement une chaîne vide "" au lieu de retirer la
contrainte NOT NULL — ce qui évite la reconstruction de table qu'imposerait
SQLite pour changer la nullabilité d'une colonne existante. C'est un choix
délibéré pour rester simple et sûr ; voir db/models.py::ProductStockUnit.

Idempotente, non destructive.

Usage :
    python -m db.migrations.002_stock_text_units
"""
from __future__ import annotations

import asyncio

from sqlalchemy import inspect, text

from db.session import engine


async def _table_columns(conn, table: str) -> set[str]:
    def _reflect(sync_conn):
        return {col["name"] for col in inspect(sync_conn).get_columns(table)}
    return await conn.run_sync(_reflect)


async def migrate() -> None:
    async with engine.begin() as conn:
        cols = await _table_columns(conn, "product_stock")

        if "text_content" in cols:
            print("[skip]    product_stock.text_content déjà en place — déjà migré.")
            return

        print("[migrate] product_stock: ajout de la colonne text_content")
        await conn.execute(text("ALTER TABLE product_stock ADD COLUMN text_content TEXT"))

    print("\nMigration terminée. Les unités de stock existantes (fichiers) ne sont pas affectées.")


if __name__ == "__main__":
    asyncio.run(migrate())
