"""
env.py Alembic — adapté pour un moteur async (aiosqlite / asyncpg).

L'URL de connexion vient de config.DATABASE_URL (donc de la variable
d'environnement DATABASE_URL), jamais d'alembic.ini, pour ne jamais avoir
deux sources de vérité différentes pour la config DB entre l'app et les
migrations.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import config as app_config
from db.models import Base

# Config Alembic standard (logging depuis alembic.ini)
alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# Metadata cible pour l'autogénération des migrations
target_metadata = Base.metadata

# Injecte l'URL réelle de l'application (jamais codée dans alembic.ini)
alembic_config.set_main_option("sqlalchemy.url", app_config.DATABASE_URL)


def run_migrations_offline() -> None:
    """Génère le SQL sans se connecter à la base (`alembic upgrade --sql`)."""
    url = alembic_config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        alembic_config.get_section(alembic_config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
