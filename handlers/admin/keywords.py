"""Panel admin — Mots-clés produit pour la recherche."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select

from db.models import Product, ProductKeyword
from db.session import get_session
from services.journal import log_action
from utils.filters import IsAdmin
from utils.states import KeywordFlow

router = Router(name="admin_keywords")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data.startswith("admin:prod:keywords:"))
async def show_keywords(callback: CallbackQuery, labels: dict) -> None:
    prod_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        product = await session.get(Product, prod_id)
        if not product:
            await callback.answer("Produit introuvable.", show_alert=True)
            return
        kw_result = await session.execute(
            select(ProductKeyword).where(ProductKeyword.product_id == prod_id)
        )
        keywords = list(kw_result.scalars().all())

    kw_list = [f"• <code>{kw.keyword}</code>" for kw in keywords]
    text = (
        f"🔑 <b>Mots-clés de « {product.name} »</b>\n\n"
        + ("\n".join(kw_list) if kw_list else "Aucun mot-clé défini.")
    )

    rows = [
        [InlineKeyboardButton(
            text=f"🗑 Supprimer : {kw.keyword[:20]}",
            callback_data=f"admin:kw:delete:{kw.id}:{prod_id}",
        )]
        for kw in keywords
    ]
    rows.append([InlineKeyboardButton(text="➕ Ajouter un mot-clé", callback_data=f"admin:kw:add:{prod_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Produit", callback_data=f"admin:prod:view:{prod_id}")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:kw:add:"))
async def start_add_keyword(callback: CallbackQuery, state: FSMContext) -> None:
    prod_id = int(callback.data.split(":")[3])
    await state.set_state(KeywordFlow.adding_keyword)
    await state.update_data(keyword_product_id=prod_id)
    await callback.message.answer(
        "Envoyez le mot-clé à ajouter (ex: <code>Crédit Agricole</code>)\n"
        "/annuler pour abandonner :"
    )
    await callback.answer()


@router.message(KeywordFlow.adding_keyword, F.text == "/annuler")
async def cancel_keyword(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Annulé.")


@router.message(KeywordFlow.adding_keyword)
async def receive_keyword(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prod_id = data.get("keyword_product_id")
    keyword = message.text.strip()

    if not keyword or len(keyword) > 100:
        await message.answer("Mot-clé invalide (max 100 caractères).")
        return

    async with get_session() as session:
        # Vérifier doublon
        existing = await session.execute(
            select(ProductKeyword).where(
                ProductKeyword.product_id == prod_id,
                ProductKeyword.keyword == keyword,
            )
        )
        if existing.scalar_one_or_none():
            await message.answer("Ce mot-clé existe déjà pour ce produit.")
            await state.clear()
            return

        session.add(ProductKeyword(product_id=prod_id, keyword=keyword))
        await session.commit()
        await log_action(session, message.from_user.id, "keyword_ajoute", f"prod={prod_id} kw={keyword}")

    await state.clear()
    await message.answer(f"✅ Mot-clé « {keyword} » ajouté.")


@router.callback_query(F.data.startswith("admin:kw:delete:"))
async def delete_keyword(callback: CallbackQuery, labels: dict) -> None:
    parts = callback.data.split(":")
    kw_id = int(parts[3])
    prod_id = int(parts[4])

    async with get_session() as session:
        kw = await session.get(ProductKeyword, kw_id)
        if kw:
            kw_text = kw.keyword
            await session.delete(kw)
            await session.commit()
            await log_action(session, callback.from_user.id, "keyword_supprime", f"prod={prod_id} kw={kw_text}")

    await callback.answer("Mot-clé supprimé.", show_alert=True)
    # Recharger la page mots-clés
    callback.data = f"admin:prod:keywords:{prod_id}"
    await show_keywords(callback, labels)
