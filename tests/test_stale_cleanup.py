"""
Test pour services/stock.py::release_stale_reservations.

Exécution :
    pip install -r requirements-dev.txt
    pytest tests/test_stale_cleanup.py -v
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, Product, ProductStockUnit, StockStatus
from services import stock


@pytest_asyncio.fixture
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield SessionLocal

    await engine.dispose()
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_only_old_reservations_are_released(db):
    """
    Une unité réservée il y a longtemps (simulant un achat interrompu par
    un crash) doit être libérée. Une unité réservée récemment (achat en
    cours normal) ne doit PAS être touchée : sinon on romprait un achat
    légitime en train de se terminer.
    """
    now = dt.datetime.utcnow()
    old_reservation = now - dt.timedelta(minutes=30)
    recent_reservation = now - dt.timedelta(seconds=5)

    async with db() as session:
        product = Product(category_id=1, name="Test", price_cents=1000)
        session.add(product)
        await session.flush()

        stale_unit = ProductStockUnit(
            product_id=product.id, telegram_file_id="f1",
            status=StockStatus.RESERVED, reserved_by=111, reserved_at=old_reservation,
        )
        fresh_unit = ProductStockUnit(
            product_id=product.id, telegram_file_id="f2",
            status=StockStatus.RESERVED, reserved_by=222, reserved_at=recent_reservation,
        )
        session.add_all([stale_unit, fresh_unit])
        await session.commit()

        cutoff = now - dt.timedelta(minutes=15)
        n_released = await stock.release_stale_reservations(session, cutoff)
        assert n_released == 1

        await session.refresh(stale_unit)
        await session.refresh(fresh_unit)

        assert stale_unit.status == StockStatus.AVAILABLE
        assert stale_unit.reserved_by is None
        assert stale_unit.reserved_at is None

        assert fresh_unit.status == StockStatus.RESERVED, (
            "Une réservation récente et légitime a été libérée par erreur"
        )
        assert fresh_unit.reserved_by == 222
