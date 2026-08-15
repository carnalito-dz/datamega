"""
Amorce le catalogue initial décrit dans le cahier des charges :
catégorie "Fiches" (Starter/Pro/Ultimate Pack) et catégorie "Carte" (vide).

Ne fait rien si des catégories existent déjà (évite les doublons au
redémarrage). Les produits sont créés en brouillon : l'admin doit
envoyer les fichiers réels via Restock puis publier depuis Telegram.
"""
from __future__ import annotations

from sqlalchemy import select

from db.models import Category, Product, ProductStatus
from db.session import get_session
from utils.money import dollars_to_cents

INITIAL_CATALOG = [
    {
        "category": {"name": "Fiches", "emoji": "📚", "position": 1},
        "products": [
            {"name": "🚀 Starter Pack", "description": "50 fiches", "price_cents": dollars_to_cents(20)},
            {"name": "💎 Pro Pack", "description": "100 fiches", "price_cents": dollars_to_cents(40)},
            {"name": "👑 Ultimate Pack ⭐", "description": "250 fiches", "price_cents": dollars_to_cents(70)},
        ],
    },
    {
        "category": {"name": "Carte", "emoji": "🗺", "position": 2},
        "products": [],
    },
]


async def seed_initial_catalog() -> None:
    async with get_session() as session:
        existing = await session.execute(select(Category).limit(1))
        if existing.scalar_one_or_none() is not None:
            return  # déjà amorcé, on ne touche à rien

        for entry in INITIAL_CATALOG:
            cat = Category(**entry["category"], is_active=True)
            session.add(cat)
            await session.flush()
            for i, p in enumerate(entry["products"]):
                session.add(Product(
                    category_id=cat.id,
                    name=p["name"],
                    description=p["description"],
                    price_cents=p["price_cents"],
                    status=ProductStatus.DRAFT,
                    position=i,
                ))
        await session.commit()
