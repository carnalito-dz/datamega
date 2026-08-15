"""
Test de non-régression pour l'anti double-crédit des dépôts NOWPayments.

On ne peut pas facilement instancier tout le serveur aiohttp ici sans un
Bot Telegram réel, donc ce test exerce directement le même mécanisme de
"réclamation atomique" que webhook/server.py::nowpayments_ipn utilise
(UPDATE ... WHERE credited=False), pour prouver que deux appels concurrents
sur le même dépôt ne peuvent jamais tous les deux "gagner" la réclamation.

Exécution :
    pip install -r requirements.txt -r requirements-dev.txt
    pytest tests/test_ipn_idempotency.py -v
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, Deposit, DepositStatus, User


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


async def _claim_deposit(session_factory, deposit_id: int) -> bool:
    """Reproduit exactement la réclamation atomique de webhook/server.py."""
    async with session_factory() as session:
        result = await session.execute(
            update(Deposit)
            .where(Deposit.id == deposit_id, Deposit.credited.is_(False))
            .values(credited=True)
        )
        await session.commit()
        return result.rowcount == 1


@pytest.mark.asyncio
async def test_concurrent_ipn_claims_only_one_wins(db):
    async with db() as session:
        user = User(telegram_id=1, username="test")
        session.add(user)
        await session.flush()
        deposit = Deposit(
            user_id=user.id,
            payment_id="pay_123",
            currency="btc",
            amount_usd_cents=5_000,
            status=DepositStatus.WAITING,
            credited=False,
        )
        session.add(deposit)
        await session.commit()
        deposit_id = deposit.id

    # Simule deux IPN quasi simultanés pour le même paiement (NOWPayments
    # peut légitimement renvoyer plusieurs notifications pour un même
    # paiement : confirming -> confirmed -> finished, ou de simples
    # retries réseau).
    results = await asyncio.gather(
        _claim_deposit(db, deposit_id),
        _claim_deposit(db, deposit_id),
    )

    assert sorted(results) == [False, True], (
        f"Attendu exactement une réclamation gagnante, obtenu : {results} "
        "(un double-crédit serait possible si les deux valent True)"
    )
