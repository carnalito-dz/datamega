"""
Tests de concurrence pour services/wallet.py.

Ces tests créent une base SQLite sur fichier temporaire (pas :memory:, pour
que plusieurs connexions concurrentes voient bien les mêmes données, comme
en production) et lancent de vraies opérations concurrentes via
asyncio.gather pour vérifier que credit()/debit() ne produisent jamais de
solde incohérent — ce qui n'était PAS garanti par l'ancienne implémentation
lire-puis-écrire.

Exécution :
    pip install -r requirements.txt -r requirements-dev.txt
    pytest tests/test_wallet_atomic.py -v
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, User, Wallet, WalletTxType
from services import wallet


@pytest_asyncio.fixture
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # SQLite crée le fichier lui-même
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield SessionLocal

    await engine.dispose()
    if os.path.exists(path):
        os.remove(path)


async def _make_user_with_balance(session_factory, balance_cents: int) -> int:
    async with session_factory() as session:
        user = User(telegram_id=1, username="test")
        session.add(user)
        await session.flush()
        session.add(Wallet(user_id=user.id, balance_cents=balance_cents))
        await session.commit()
        return user.id


@pytest.mark.asyncio
async def test_concurrent_debits_never_go_negative(db):
    """
    Deux débits concurrents de 60 chacun sur un solde de 100 : un seul doit
    réussir, l'autre doit lever InsufficientBalance. Le solde final doit
    rester >= 0 (jamais négatif), et exactement un débit doit être appliqué.
    """
    user_id = await _make_user_with_balance(db, balance_cents=10_000)  # 100.00$

    async def try_debit():
        async with db() as session:
            try:
                await wallet.debit(session, user_id, 6_000, WalletTxType.PURCHASE)
                return "ok"
            except wallet.InsufficientBalance:
                return "insufficient"

    results = await asyncio.gather(try_debit(), try_debit())

    assert sorted(results) == ["insufficient", "ok"], (
        f"Attendu exactement un succès et un échec, obtenu : {results}"
    )

    async with db() as session:
        w = await wallet.get_wallet(session, user_id)
        assert w.balance_cents == 4_000, (
            f"Solde final incohérent : {w.balance_cents} centimes "
            f"(attendu 4000 = 10000 - 6000, un seul débit appliqué)"
        )
        assert w.balance_cents >= 0


@pytest.mark.asyncio
async def test_concurrent_credits_are_not_lost(db):
    """
    Dix crédits concurrents de 100 centimes chacun sur un solde à 0 doivent
    tous être appliqués : le solde final doit être exactement 1000, pas
    moins (ce qui arriverait avec un lire-puis-écrire non protégé où des
    écritures concurrentes s'écrasent entre elles — "lost update").
    """
    user_id = await _make_user_with_balance(db, balance_cents=0)

    async def do_credit():
        async with db() as session:
            await wallet.credit(session, user_id, 100, WalletTxType.ADMIN_CREDIT)

    await asyncio.gather(*[do_credit() for _ in range(10)])

    async with db() as session:
        w = await wallet.get_wallet(session, user_id)
        assert w.balance_cents == 1_000, (
            f"Solde final = {w.balance_cents}, attendu 1000 : "
            "des crédits concurrents ont été perdus."
        )
