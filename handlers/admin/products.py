from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import Category, Product, ProductStatus
from db.session import get_session
from keyboards.admin_kb import (
    category_picker_kb,
    finish_files_kb,
    product_detail_admin_kb,
    product_search_results_kb,
    products_admin_kb,
    skip_kb,
    trash_kb,
)
from services import stock
from services.journal import log_action
from utils.filters import IsAdmin
from utils.formatting import fmt_money
from utils.money import InvalidAmount, parse_usd_to_cents
from utils.states import KeywordImportFlow, KeywordFlow, ProductFlow, RestockFlow

router = Router(name="admin_products")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _products_not_deleted(session) -> list[Product]:
    result = await session.execute(
        select(Product).where(Product.status != ProductStatus.DELETED).order_by(Product.position)
    )
    return list(result.scalars().all())


async def _deleted_products(session) -> list[Product]:
    result = await session.execute(
        select(Product).where(Product.status == ProductStatus.DELETED)
    )
    return list(result.scalars().all())


async def _active_categories(session) -> list[Category]:
    result = await session.execute(select(Category).where(Category.is_active.is_(True)))
    return list(result.scalars().all())


@router.callback_query(F.data == "admin:products")
async def list_products(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        products = await _products_not_deleted(session)
    await callback.message.edit_text(
        "📦 <b>Produits</b>\n\n📝 brouillon · ✅ publié",
        reply_markup=products_admin_kb(products, labels),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:prod:view:"))
async def view_product(callback: CallbackQuery, labels: dict[str, str]) -> None:
    prod_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        p = await session.get(Product, prod_id)
        if not p:
            await callback.answer("Introuvable.", show_alert=True)
            return
        available = await stock.count_available(session, prod_id)
    text = (
        f"<b>{p.name}</b>  <code>#{p.id}</code>\n{p.description or ''}\n\n"
        f"💵 Prix : {fmt_money(p.price_cents)}\n"
        f"📦 Stock disponible : {available}\n"
        f"Statut : {p.status.value}"
    )
    await callback.message.answer(text, reply_markup=product_detail_admin_kb(p, labels))
    await callback.answer()


# --- Recherche produit (référence #ID ou titre) ---
@router.callback_query(F.data == "admin:prod:search")
async def start_search_product(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProductFlow.searching)
    await callback.message.answer(
        "🔎 Envoyez le <b>numéro de référence</b> (ex : <code>12</code> ou <code>#12</code>) "
        "ou une partie du <b>titre</b> du produit :"
    )
    await callback.answer()


@router.message(ProductFlow.searching)
async def search_product(message: Message, state: FSMContext, labels: dict[str, str]) -> None:
    query = message.text.strip().lstrip("#")
    async with get_session() as session:
        if query.isdigit():
            result = await session.execute(
                select(Product).where(Product.id == int(query), Product.status != ProductStatus.DELETED)
            )
        else:
            result = await session.execute(
                select(Product)
                .where(Product.name.ilike(f"%{query}%"), Product.status != ProductStatus.DELETED)
                .order_by(Product.position)
                .limit(20)
            )
        matches = list(result.scalars().all())

    await state.clear()
    if not matches:
        await message.answer("Aucun produit trouvé pour cette recherche.")
        return
    if len(matches) == 1:
        p = matches[0]
        async with get_session() as session:
            available = await stock.count_available(session, p.id)
        text = (
            f"<b>{p.name}</b>  <code>#{p.id}</code>\n{p.description or ''}\n\n"
            f"💵 Prix : {fmt_money(p.price_cents)}\n"
            f"📦 Stock disponible : {available}\n"
            f"Statut : {p.status.value}"
        )
        await message.answer(text, reply_markup=product_detail_admin_kb(p, labels))
        return
    await message.answer(
        f"🔎 {len(matches)} résultat(s) :",
        reply_markup=product_search_results_kb(matches, labels),
    )


# --- Corbeille ---
@router.callback_query(F.data == "admin:prod:trash")
async def show_trash(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        deleted = await _deleted_products(session)
    if not deleted:
        await callback.answer("Corbeille vide.", show_alert=True)
        return
    await callback.message.edit_text("🗑 <b>Corbeille</b>", reply_markup=trash_kb(deleted, labels))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:prod:restore:"))
async def restore_product(callback: CallbackQuery, labels: dict[str, str]) -> None:
    prod_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        p = await session.get(Product, prod_id)
        if p:
            p.status = ProductStatus.DRAFT
            await session.commit()
            await log_action(session, callback.from_user.id, "produit_restaure", p.name)
    await callback.answer("Produit restauré en brouillon.", show_alert=True)
    await show_trash(callback, labels)


@router.callback_query(F.data.startswith("admin:prod:delete:"))
async def delete_product(callback: CallbackQuery, labels: dict[str, str]) -> None:
    prod_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        p = await session.get(Product, prod_id)
        if p:
            p.status = ProductStatus.DELETED
            await session.commit()
            await log_action(session, callback.from_user.id, "produit_supprime", p.name)
    await callback.answer("Produit déplacé vers la corbeille.", show_alert=True)
    await list_products(callback, labels)


@router.callback_query(F.data.startswith("admin:prod:togglepub:"))
async def toggle_publish(callback: CallbackQuery, labels: dict[str, str]) -> None:
    prod_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        p = await session.get(Product, prod_id)
        if not p:
            await callback.answer("Introuvable.", show_alert=True)
            return
        p.status = ProductStatus.DRAFT if p.status == ProductStatus.PUBLISHED else ProductStatus.PUBLISHED
        await session.commit()
        await log_action(session, callback.from_user.id, "produit_statut", f"{p.name} -> {p.status.value}")
    await callback.answer(f"Statut : {p.status.value}", show_alert=True)
    await view_product(callback, labels)


# --- Ajout produit (wizard) ---
@router.callback_query(F.data == "admin:prod:add")
async def start_add_product(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProductFlow.adding_name)
    await callback.message.answer("Envoyez le <b>nom</b> du nouveau produit :")
    await callback.answer()


@router.message(ProductFlow.adding_name)
async def add_product_name(message: Message, state: FSMContext, labels: dict[str, str]) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(ProductFlow.adding_description)
    await message.answer(
        "Envoyez la <b>description</b> du produit :", reply_markup=skip_kb("prod:skip_desc", labels)
    )


@router.message(ProductFlow.adding_description)
async def add_product_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text.strip())
    await _ask_price(message, state)


@router.callback_query(ProductFlow.adding_description, F.data == "prod:skip_desc")
async def skip_product_description(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(description=None)
    await _ask_price(callback.message, state)
    await callback.answer()


async def _ask_price(message: Message, state: FSMContext) -> None:
    await state.set_state(ProductFlow.adding_price)
    await message.answer("Envoyez le <b>prix</b> en USD (exemple : 20) :")


@router.message(ProductFlow.adding_price)
async def add_product_price(message: Message, state: FSMContext) -> None:
    try:
        price_cents = parse_usd_to_cents(message.text)
    except InvalidAmount:
        await message.answer("Prix invalide, réessayez (exemple : 20).")
        return
    await state.update_data(price_cents=price_cents)
    async with get_session() as session:
        cats = await _active_categories(session)
    if not cats:
        await message.answer("Aucune catégorie active. Créez d'abord une catégorie.")
        await state.clear()
        return
    await state.set_state(ProductFlow.choosing_category)
    await message.answer(
        "Choisissez la <b>catégorie</b> :", reply_markup=category_picker_kb(cats, "prod:setcat")
    )


@router.callback_query(ProductFlow.choosing_category, F.data.startswith("prod:setcat:"))
async def add_product_category(callback: CallbackQuery, state: FSMContext, labels: dict[str, str]) -> None:
    cat_id = int(callback.data.split(":")[2])
    await state.update_data(category_id=cat_id)
    await state.set_state(ProductFlow.adding_image)
    await callback.message.answer(
        "Envoyez l'<b>image</b> du produit (ou passez cette étape) :",
        reply_markup=skip_kb("prod:skip_image", labels),
    )
    await callback.answer()


@router.message(ProductFlow.adding_image, F.photo)
async def add_product_image(message: Message, state: FSMContext, labels: dict[str, str]) -> None:
    file_id = message.photo[-1].file_id
    await state.update_data(image_file_id=file_id)
    await _finish_product_creation(message, state, labels)


@router.callback_query(ProductFlow.adding_image, F.data == "prod:skip_image")
async def skip_product_image(callback: CallbackQuery, state: FSMContext, labels: dict[str, str]) -> None:
    await state.update_data(image_file_id=None)
    await _finish_product_creation(callback.message, state, labels)
    await callback.answer()


async def _finish_product_creation(message: Message, state: FSMContext, labels: dict[str, str]) -> None:
    data = await state.get_data()
    async with get_session() as session:
        max_pos = await session.execute(select(Product.position).order_by(Product.position.desc()).limit(1))
        last = max_pos.scalar_one_or_none() or 0
        product = Product(
            category_id=data["category_id"],
            name=data["name"],
            description=data.get("description"),
            price_cents=data["price_cents"],
            image_file_id=data.get("image_file_id"),
            status=ProductStatus.DRAFT,
            position=last + 1,
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        await log_action(session, message.from_user.id, "produit_cree", product.name)

    await state.update_data(new_product_id=product.id)
    await state.set_state(ProductFlow.adding_files)
    await message.answer(
        f"✅ Produit « {product.name} » (<code>#{product.id}</code>) créé en brouillon.\n\n"
        f"Envoyez maintenant le stock, un par un ou plusieurs à la fois :\n"
        f"• Envoyez un <b>fichier</b> → 1 unité de stock\n"
        f"• Écrivez un <b>texte</b> (code, identifiants, lien...) → 1 unité de stock\n"
        f"• Pour plusieurs unités texte d'un coup, séparez-les par une ligne "
        f"« <code>---</code> », exemple :\n"
        f"<code>CODE-AAA-111\n---\nCODE-BBB-222\n---\nCODE-CCC-333</code>\n\n"
        f"Puis appuyez sur « Terminer » quand vous avez fini.",
        reply_markup=finish_files_kb("prod:finish_files", labels),
    )


@router.message(ProductFlow.adding_files, F.document)
async def add_product_stock_file(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["new_product_id"]
    async with get_session() as session:
        await stock.add_file_stock_units(
            session, product_id, [(message.document.file_id, message.document.file_name)]
        )
    await message.answer("📥 Fichier ajouté au stock.")


@router.message(ProductFlow.adding_files, F.text, ~F.text.startswith("/"))
async def add_product_stock_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["new_product_id"]
    entries = stock.parse_text_stock_entries(message.text)
    if not entries:
        await message.answer("Texte vide, réessayez.")
        return
    async with get_session() as session:
        await stock.add_text_stock_units(session, product_id, entries)
    n = len(entries)
    await message.answer(f"📥 {n} unité(s) de stock ajoutée(s) au stock." if n > 1 else "📥 Unité de stock ajoutée.")


@router.callback_query(ProductFlow.adding_files, F.data == "prod:finish_files")
async def finish_add_files(callback: CallbackQuery, state: FSMContext, labels: dict) -> None:
    data = await state.get_data()
    product_id = data["new_product_id"]
    async with get_session() as session:
        available = await stock.count_available(session, product_id)

    # Proposer d'ajouter des mots-clés directement
    await state.set_state(ProductFlow.adding_keywords)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Passer (sans mots-clés)", callback_data="prod:skip_keywords")],
    ])
    text_kw = (
        "✅ Stock ajouté ({n} unité(s)).\n\n"
        "🔑 <b>Mots-clés</b> (optionnel)\n\n"
        "Envoyez les mots-clés <b>un par un</b> ou <b>plusieurs séparés par des virgules</b> :\n"
        "<code>Crédit Agricole, banque, fermeture</code>\n\n"
        "Ces mots-clés permettront aux clients de retrouver cet article par recherche.\n"
        "Appuyez sur ⏭ Passer si vous n'en voulez pas pour l'instant."
    ).replace("{n}", str(available))
    await callback.message.answer(text_kw, reply_markup=kb)
    await callback.answer()


@router.callback_query(ProductFlow.adding_keywords, F.data == "prod:skip_keywords")
async def skip_product_keywords(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["new_product_id"]
    await state.clear()
    await callback.message.edit_text(
        f"✅ Produit <code>#{product_id}</code> prêt.\n"
        "Pensez à le <b>publier</b> depuis la fiche produit."
    )
    await callback.answer()


@router.message(ProductFlow.adding_keywords, F.text)
async def add_product_keywords(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["new_product_id"]

    # Parser les mots-clés (séparés par virgule ou retour à la ligne)
    import re
    raw = re.split(r"[,\n]", message.text)
    keywords = [k.strip() for k in raw if k.strip()]
    if not keywords:
        await message.answer("Aucun mot-clé détecté. Réessayez ou /annuler.")
        return

    from db.models import ProductKeyword
    from sqlalchemy import select
    added = []
    skipped = []
    async with get_session() as session:
        for kw in keywords:
            if len(kw) > 100:
                skipped.append(kw[:20] + "…")
                continue
            existing = await session.execute(
                select(ProductKeyword).where(
                    ProductKeyword.product_id == product_id,
                    ProductKeyword.keyword == kw,
                )
            )
            if existing.scalar_one_or_none():
                skipped.append(kw)
                continue
            session.add(ProductKeyword(product_id=product_id, keyword=kw))
            added.append(kw)
        await session.commit()
        from services.journal import log_action
        await log_action(session, message.from_user.id, "keywords_ajoutes",
                         f"prod={product_id} kws={added}")

    lines = []
    if added:
        lines.append(f"✅ {len(added)} mot(s)-clé(s) ajouté(s) : {', '.join(added)}")
    if skipped:
        lines.append(f"⚠️ Ignorés (doublon ou trop long) : {', '.join(skipped)}")
    lines.append("\nEnvoyez d'autres mots-clés ou appuyez sur ⏭ Passer pour terminer.")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Terminer", callback_data="prod:skip_keywords")],
    ])
    await message.answer("\n".join(lines), reply_markup=kb)


# --- Restock produit existant ---
@router.callback_query(F.data.startswith("admin:prod:restock:"))
async def start_restock(callback: CallbackQuery, state: FSMContext, labels: dict[str, str]) -> None:
    prod_id = int(callback.data.split(":")[3])
    await state.update_data(restock_product_id=prod_id)
    await state.set_state(RestockFlow.sending_files)
    await callback.message.answer(
        "Envoyez le stock à ajouter :\n"
        "• Un <b>fichier</b> → 1 unité\n"
        "• Un <b>texte</b> → 1 unité (plusieurs d'un coup : séparez-les par une ligne « <code>---</code> »)\n\n"
        "Puis « Terminer ».",
        reply_markup=finish_files_kb("prod:finish_restock", labels),
    )
    await callback.answer()


@router.message(RestockFlow.sending_files, F.document)
async def restock_receive_file(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["restock_product_id"]
    async with get_session() as session:
        await stock.add_file_stock_units(
            session, product_id, [(message.document.file_id, message.document.file_name)]
        )
    await message.answer("📥 Fichier ajouté au stock.")


@router.message(RestockFlow.sending_files, F.text, ~F.text.startswith("/"))
async def restock_receive_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["restock_product_id"]
    entries = stock.parse_text_stock_entries(message.text)
    if not entries:
        await message.answer("Texte vide, réessayez.")
        return
    async with get_session() as session:
        await stock.add_text_stock_units(session, product_id, entries)
    n = len(entries)
    await message.answer(f"📥 {n} unité(s) de stock ajoutée(s) au stock." if n > 1 else "📥 Unité de stock ajoutée.")


@router.callback_query(RestockFlow.sending_files, F.data == "prod:finish_restock")
async def finish_restock(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["restock_product_id"]
    async with get_session() as session:
        available = await stock.count_available(session, product_id)
        p = await session.get(Product, product_id)
        await log_action(session, callback.from_user.id, "restock", f"{p.name} -> {available} dispo")
    await state.clear()
    await callback.message.answer(f"✅ Restock terminé. Stock disponible : {available}.")
    await callback.answer()


# --- Édition champ par champ ---
FIELD_LABELS = {
    "name": "nom",
    "description": "description",
    "price": "prix",
    "image": "image",
}


@router.callback_query(F.data.startswith("admin:prod:edit:"))
async def start_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, _, field, prod_id = callback.data.split(":")
    await state.update_data(edit_product_id=int(prod_id), edit_field=field)
    await state.set_state(ProductFlow.editing_value)
    label = FIELD_LABELS.get(field, field)
    if field == "image":
        await callback.message.answer(f"Envoyez la nouvelle {label} (photo) :")
    else:
        await callback.message.answer(f"Envoyez la nouvelle valeur pour « {label} » :")
    await callback.answer()


@router.message(ProductFlow.editing_value, F.photo)
async def receive_edit_image(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("edit_field") != "image":
        return
    async with get_session() as session:
        p = await session.get(Product, data["edit_product_id"])
        if p:
            p.image_file_id = message.photo[-1].file_id
            await session.commit()
            await log_action(session, message.from_user.id, "produit_image_maj", p.name)
    await state.clear()
    await message.answer("✅ Image mise à jour.")


@router.message(ProductFlow.editing_value)
async def receive_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("edit_field")
    prod_id = data.get("edit_product_id")
    if field == "image":
        await message.answer("Merci d'envoyer une photo pour ce champ.")
        return
    async with get_session() as session:
        p = await session.get(Product, prod_id)
        if not p:
            await message.answer("Produit introuvable.")
            await state.clear()
            return
        if field == "price":
            try:
                p.price_cents = parse_usd_to_cents(message.text)
            except InvalidAmount:
                await message.answer("Prix invalide, réessayez.")
                return
        elif field == "name":
            p.name = message.text.strip()
        elif field == "description":
            p.description = message.text.strip()
        await session.commit()
        await log_action(session, message.from_user.id, "produit_modifie", f"{p.name} champ={field}")
    await state.clear()
    await message.answer(f"✅ {FIELD_LABELS.get(field, field).capitalize()} mis à jour.")
