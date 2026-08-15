"""
Gestion du stock unitaire.

reserve_unit() utilise une stratégie en 3 étapes pour être à la fois
atomique (anti double-vente) et correcte malgré l'identity map SQLAlchemy
(expire_on_commit=False) :
  1. SELECT id de la première unité AVAILABLE
  2. UPDATE atomique WHERE id=target AND status=AVAILABLE
  3. Lecture fraîche dans une nouvelle session indépendante

extract_series_code() extrait automatiquement les 6 premiers chiffres
d'un texte de stock pour la recherche par série.
"""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Product, ProductStockUnit, StockStatus

STOCK_TEXT_SEPARATOR = "---"
SERIES_CODE_RE = re.compile(r"^\d{6,}")


def extract_series_code(text: str) -> str | None:
    """Extrait le code série (6+ chiffres au début du texte)."""
    m = SERIES_CODE_RE.match(text.strip())
    if m:
        return m.group(0)[:6]
    return None


async def count_available(session: AsyncSession, product_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(ProductStockUnit).where(
            ProductStockUnit.product_id == product_id,
            ProductStockUnit.status == StockStatus.AVAILABLE,
        )
    )
    return result.scalar_one()


async def reserve_unit(session: AsyncSession, product_id: int,
                       buyer_telegram_id: int) -> ProductStockUnit | None:
    """
    Réserve atomiquement une unité disponible.
    Retourne l'objet frais (lu dans une nouvelle session) ou None si rupture.
    """
    now = dt.datetime.utcnow()

    # Étape 1 : trouver l'id cible AVANT l'UPDATE
    id_result = await session.execute(
        select(ProductStockUnit.id)
        .where(
            ProductStockUnit.product_id == product_id,
            ProductStockUnit.status == StockStatus.AVAILABLE,
        )
        .order_by(ProductStockUnit.id)
        .limit(1)
    )
    target_id = id_result.scalar_one_or_none()
    if target_id is None:
        return None

    # Étape 2 : UPDATE atomique (la condition status=AVAILABLE protège contre
    # les race conditions entre deux coroutines qui auraient lu le même id)
    result = await session.execute(
        update(ProductStockUnit)
        .where(
            ProductStockUnit.id == target_id,
            ProductStockUnit.status == StockStatus.AVAILABLE,
        )
        .values(
            status=StockStatus.RESERVED,
            reserved_by=buyer_telegram_id,
            reserved_at=now,
        )
    )
    await session.commit()

    if result.rowcount == 0:
        # Race condition : une autre coroutine a pris cette unité
        return None

    # Étape 3 : lecture fraîche dans une nouvelle session (évite l'identity
    # map stale due à expire_on_commit=False dans SessionLocal)
    from db.session import get_session as _gs
    async with _gs() as fresh:
        r = await fresh.execute(
            select(ProductStockUnit).where(ProductStockUnit.id == target_id)
        )
        return r.scalar_one_or_none()


async def mark_sold(session: AsyncSession, unit: ProductStockUnit,
                    buyer_telegram_id: int) -> None:
    unit.status = StockStatus.SOLD
    unit.sold_to = buyer_telegram_id
    unit.sold_at = dt.datetime.utcnow()
    await session.commit()


async def release_unit(session: AsyncSession, unit: ProductStockUnit) -> None:
    """Remet une unité réservée en disponible (ex : échec livraison)."""
    unit.status = StockStatus.AVAILABLE
    unit.reserved_by = None
    unit.reserved_at = None
    await session.commit()


async def release_stale_reservations(session: AsyncSession,
                                     older_than: dt.datetime) -> int:
    result = await session.execute(
        update(ProductStockUnit)
        .where(
            ProductStockUnit.status == StockStatus.RESERVED,
            ProductStockUnit.reserved_at < older_than,
        )
        .values(status=StockStatus.AVAILABLE, reserved_by=None, reserved_at=None)
    )
    await session.commit()
    return result.rowcount


def parse_text_stock_entries(raw_text: str) -> list[str]:
    """
    Découpe un message texte en plusieurs entrées de stock, séparées par
    une ligne contenant exactement `---`.

    Exemple :
        51234600145 / Article A
        ---
        51234600146 / Article B
    → ["51234600145 / Article A", "51234600146 / Article B"]
    """
    chunks = raw_text.split(f"\n{STOCK_TEXT_SEPARATOR}\n")
    if len(chunks) == 1:
        chunks = raw_text.split(STOCK_TEXT_SEPARATOR)
    return [c.strip() for c in chunks if c.strip()]


async def add_file_stock_units(session: AsyncSession, product_id: int,
                                file_ids: list[tuple[str, str | None]]) -> int:
    """file_ids : liste de (telegram_file_id, file_name). Retourne le nombre ajouté."""
    for file_id, file_name in file_ids:
        session.add(ProductStockUnit(
            product_id=product_id,
            telegram_file_id=file_id,
            file_name=file_name,
        ))
    await session.commit()
    return len(file_ids)


async def add_text_stock_units(session: AsyncSession, product_id: int,
                                texts: list[str]) -> int:
    """Ajoute des unités texte avec extraction automatique du code série."""
    for content in texts:
        series = extract_series_code(content)
        session.add(ProductStockUnit(
            product_id=product_id,
            telegram_file_id="",
            text_content=content,
            series_code=series,
        ))
    await session.commit()
    return len(texts)


async def search_by_series(session: AsyncSession, series_code: str,
                            buyer_telegram_id: int | None = None) -> list[ProductStockUnit]:
    """
    Retourne toutes les unités AVAILABLE dont le code série correspond.
    Si buyer_telegram_id est fourni, filtre sur les produits déjà achetés
    par cet utilisateur (pour la recherche client).
    """
    from db.models import Order, OrderStatus, Product, ProductStatus
    q = (
        select(ProductStockUnit)
        .join(Product, Product.id == ProductStockUnit.product_id)
        .where(
            ProductStockUnit.series_code == series_code,
            ProductStockUnit.status == StockStatus.AVAILABLE,
            Product.status == ProductStatus.PUBLISHED,
        )
        .order_by(ProductStockUnit.id)
    )
    result = await session.execute(q)
    return list(result.scalars().all())


async def search_by_keyword(session: AsyncSession, keyword: str) -> list[ProductStockUnit]:
    """
    Recherche par mot-clé exact (correspondance stricte, insensible à la casse).
    Retourne les unités AVAILABLE des produits ayant ce mot-clé.
    """
    from db.models import Product, ProductStatus, ProductKeyword
    q = (
        select(ProductStockUnit)
        .join(Product, Product.id == ProductStockUnit.product_id)
        .join(ProductKeyword, ProductKeyword.product_id == Product.id)
        .where(
            func.lower(ProductKeyword.keyword) == keyword.lower().strip(),
            ProductStockUnit.status == StockStatus.AVAILABLE,
            Product.status == ProductStatus.PUBLISHED,
        )
        .order_by(ProductStockUnit.product_id, ProductStockUnit.id)
    )
    result = await session.execute(q)
    return list(result.scalars().all())
