from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import case, func, select

from db.models import Product, ProductStatus, ProductStockUnit, StockStatus
from db.session import get_session
from keyboards.admin_kb import back_to_admin_kb
from services import settings as settings_service
from utils.filters import IsAdmin

router = Router(name="admin_stock")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:stock")
async def stock_overview(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Product).where(Product.status != ProductStatus.DELETED).order_by(Product.position)
        )
        products = list(result.scalars().all())

        # Une seule requête agrégée pour TOUS les produits (au lieu de 2
        # requêtes par produit dans une boucle) : reste performant même
        # avec un catalogue de plusieurs milliers de produits.
        counts_result = await session.execute(
            select(
                ProductStockUnit.product_id,
                func.sum(case((ProductStockUnit.status == StockStatus.AVAILABLE, 1), else_=0)),
                func.sum(case((ProductStockUnit.status == StockStatus.SOLD, 1), else_=0)),
            ).group_by(ProductStockUnit.product_id)
        )
        counts_by_product = {
            product_id: (n_avail, n_sold)
            for product_id, n_avail, n_sold in counts_result.all()
        }

        low_stock_threshold = await settings_service.get_low_stock_threshold(session)

        lines = ["📥 <b>Stock par produit</b>\n"]
        for p in products:
            n_avail, n_sold = counts_by_product.get(p.id, (0, 0))
            flag = " ⚠️" if n_avail <= low_stock_threshold else ""
            lines.append(f"{p.name} — dispo : {n_avail}{flag} · vendus : {n_sold}")

    if len(lines) == 1:
        lines.append("Aucun produit.")
    await callback.message.edit_text("\n".join(lines), reply_markup=back_to_admin_kb(labels))
    await callback.answer()
