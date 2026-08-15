"""
Moteur et session SQLAlchemy async.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import config
from db.models import Base

# S'assure que le dossier data/ existe pour SQLite
if config.DATABASE_URL.startswith("sqlite"):
    os.makedirs("data", exist_ok=True)

engine = create_async_engine(config.DATABASE_URL, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Crée les tables si elles n'existent pas encore (migration simple)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session():
    async with SessionLocal() as session:
        yield session
