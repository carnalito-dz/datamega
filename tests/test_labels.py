"""
Test pour services/labels.py.

Exécution :
    pip install -r requirements-dev.txt
    pytest tests/test_labels.py -v
"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base
from services import labels as labels_service


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
async def test_defaults_before_any_override(db):
    async with db() as session:
        resolved = await labels_service.get_labels(session)
    # Toutes les clés connues doivent être présentes, avec leur défaut.
    for lb in labels_service.LABELS:
        assert resolved[lb.key] == lb.default


@pytest.mark.asyncio
async def test_set_label_overrides_and_get_labels_reflects_it(db):
    async with db() as session:
        await labels_service.set_label(session, "shop_buy", "🛍️ Commander")
        resolved = await labels_service.get_labels(session)

    assert resolved["shop_buy"] == "🛍️ Commander"
    # Les autres clés ne doivent pas être affectées.
    assert resolved["shop_cancel"] == labels_service.get_definition("shop_cancel").default


@pytest.mark.asyncio
async def test_reset_label_reverts_to_default(db):
    async with db() as session:
        await labels_service.set_label(session, "shop_buy", "🛍️ Commander")
        default_text = await labels_service.reset_label(session, "shop_buy")
        resolved = await labels_service.get_labels(session)

    assert default_text == labels_service.get_definition("shop_buy").default
    assert resolved["shop_buy"] == labels_service.get_definition("shop_buy").default


@pytest.mark.asyncio
async def test_set_label_rejects_empty_value(db):
    async with db() as session:
        with pytest.raises(ValueError):
            await labels_service.set_label(session, "shop_buy", "   ")
