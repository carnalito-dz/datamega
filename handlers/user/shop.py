"""
Boutique client — VERSION COMPLÈTE :
  - Navigation catégories / produits
  - Recherche par code série ou mot-clé
  - Sélection de quantité
  - Achat avec code promo
  - Re-livraison d'un fichier déjà acheté
  - Points de fidélité gagnés à chaque achat
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select

from db.models import (
    Category, Order, OrderStatus, Product, ProductStatus,
    ProductStockUnit, StockStatus,
)
from db.session import get_session
from keyboards.user_kb import (
    categories_kb, confirm_purchase_kb, product_detail_kb, products_kb,
    quantity_kb, search_result_kb,
)
from services import delivery, loyalty, notify, stock
from services.messages import get_message
from services.promo import PromoError, validate_and_apply, record_use
from services.wallet import InsufficientBalance, get_or_create_user, get_wallet, debit, credit, WalletTxType
from utils.filters import MatchesLabel
from utils.formatting import fmt_money
from utils.states import PromoFlow, QuantityFlow, SearchFlow

router = Router(name="user_shop")

# Garde anti double-achat (UX — la sécurité financière est garantie par l'atomicité)
_purchases_in_progress: set[tuple[int, int]] = set()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _active_categories(session) -> list[Category]:
    r = await session.execute(
        select(Category)
        .where(Category.is_active.is_(True))
        .order_by(Category.position)
    )
    return list(r.scalars().all())


async def _published_products(session, category_id: int) -> list[Product]:
    r = await session.execute(
        select(Product)
        .where(
            Product.category_id == category_id,
            Product.status == ProductStatus.PUBLISHED,
        )
        .order_by(Product.position)
    )
    return list(r.scalars().all())


# ── Navigation ───────────────────────────────────────────────────────────────

@router.message(MatchesLabel("menu_shop"))
async def open_shop(message: Message, labels: dict) -> None:
    async with get_session() as session:
        categories = await _active_categories(session)
    if not categories:
        await message.answer("Aucune catégorie disponible pour le moment.")
        return
    await message.answer(
        "Choisissez une catégorie :",
        reply_markup=categories_kb(categories),
    )


@router.callback_query(F.data == "shop:categories")
async def back_to_categories(callback: CallbackQuery) -> None:
    async with get_session() as session:
        categories = await _active_categories(session)
    await callback.message.edit_text(
        "Choisissez une catégorie :",
        reply_markup=categories_kb(categories),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("shop:cat:"))
async def show_products(callback: CallbackQuery, labels: dict) -> None:
    category_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        products = await _published_products(session, category_id)
    if not products:
        await callback.answer(
            "Aucun produit dans cette catégorie pour le moment.",
            show_alert=True,
        )
        return
    await callback.message.edit_text(
        "Produits disponibles :",
        reply_markup=products_kb(products, category_id, labels),
    )
    await callback.answer()


@router.callback_query(F.data == "shop:back_to_products")
async def back_to_products(callback: CallbackQuery) -> None:
    await back_to_categories(callback)


# ── Fiche produit ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("shop:product:"))
async def show_product(callback: CallbackQuery, labels: dict) -> None:
    product_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        product = await session.get(Product, product_id)
        if not product or product.status != ProductStatus.PUBLISHED:
            await callback.answer("Produit indisponible.", show_alert=True)
            return
        available = await stock.count_available(session, product_id)
        out_msg = await get_message(session, "out_of_stock")

    caption = (
        f"<b>{product.name}</b>\n\n"
        f"{product.description or ''}\n\n"
        f"💵 Prix : {fmt_money(product.price_cents)}\n"
        f"📦 Stock : {available} disponible(s)\n"
    )
    if available <= 0:
        caption += f"\n{out_msg}"

    kb = product_detail_kb(product_id, in_stock=available > 0, labels=labels)
    if product.image_file_id:
        await callback.message.answer_photo(
            product.image_file_id, caption=caption, reply_markup=kb
        )
        await callback.message.delete()
    else:
        await callback.message.edit_text(caption, reply_markup=kb)
    await callback.answer()


# ── Sélection de quantité ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("shop:buy:"))
async def start_purchase(callback: CallbackQuery, state: FSMContext, labels: dict) -> None:
    product_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        product = await session.get(Product, product_id)
        if not product or product.status != ProductStatus.PUBLISHED:
            await callback.answer("Produit indisponible.", show_alert=True)
            return
        available = await stock.count_available(session, product_id)
        if available <= 0:
            await callback.answer("Rupture de stock.", show_alert=True)
            return
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.username, callback.from_user.full_name,
        )
        wallet_obj = await get_wallet(session, user.id)

    max_qty = min(available, 10)  # max 10 à la fois

    await state.set_state(QuantityFlow.choosing_quantity)
    await state.update_data(
        product_id=product_id,
        product_name=product.name,
        price_cents=product.price_cents,
        available=available,
        balance_cents=wallet_obj.balance_cents,
    )
    await callback.message.answer(
        f"<b>{product.name}</b>\n"
        f"Prix unitaire : {fmt_money(product.price_cents)}\n"
        f"Stock disponible : {available}\n"
        f"Votre solde : {fmt_money(wallet_obj.balance_cents)}\n\n"
        f"Combien d'unités souhaitez-vous acheter ?",
        reply_markup=quantity_kb(max_qty, product_id),
    )
    await callback.answer()


@router.callback_query(QuantityFlow.choosing_quantity, F.data.startswith("shop:qty:"))
async def choose_quantity(callback: CallbackQuery, state: FSMContext, labels: dict) -> None:
    parts = callback.data.split(":")
    qty = int(parts[2])
    data = await state.get_data()

    total_cents = data["price_cents"] * qty
    balance = data["balance_cents"]

    await state.update_data(quantity=qty, total_cents=total_cents)

    confirm_text = (
        f"<b>Récapitulatif de votre commande</b>\n\n"
        f"Produit : {data['product_name']}\n"
        f"Quantité : {qty}\n"
        f"Prix unitaire : {fmt_money(data['price_cents'])}\n"
        f"Total : {fmt_money(total_cents)}\n"
        f"Votre solde : {fmt_money(balance)}\n\n"
        f"Avez-vous un code promo ? Entrez-le maintenant ou confirmez directement."
    )

    rows = [
        [InlineKeyboardButton(
            text=f"✅ Confirmer ({fmt_money(total_cents)})",
            callback_data=f"shop:confirm_qty:{data['product_id']}:{qty}:0"
        )],
        [InlineKeyboardButton(text="🎟 J'ai un code promo", callback_data="shop:enter_promo")],
        [InlineKeyboardButton(text="❌ Annuler", callback_data="shop:cancel")],
    ]
    await callback.message.edit_text(
        confirm_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "shop:enter_promo")
async def enter_promo(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoFlow.entering_code)
    await callback.message.answer(
        "Envoyez votre code promo (/annuler pour ignorer) :"
    )
    await callback.answer()


@router.message(PromoFlow.entering_code)
async def receive_promo_code(message: Message, state: FSMContext, labels: dict) -> None:
    if message.text.strip() == "/annuler":
        await state.set_state(QuantityFlow.choosing_quantity)
        await message.answer("Code promo ignoré.")
        return

    data = await state.get_data()
    product_id = data.get("product_id")
    qty = data.get("quantity", 1)
    price_cents = data.get("price_cents", 0)
    total_cents = price_cents * qty

    async with get_session() as session:
        user = await get_or_create_user(
            session, message.from_user.id,
            message.from_user.username, message.from_user.full_name,
        )
        try:
            final_price, promo = await validate_and_apply(
                session, message.text.strip(), user.id, total_cents
            )
        except PromoError as e:
            await message.answer(f"❌ {e}\nRéessayez ou envoyez /annuler.")
            return

    reduction = total_cents - final_price
    await state.update_data(
        promo_code=message.text.strip().upper(),
        promo_final_cents=final_price,
        promo_reduction=reduction,
    )

    rows = [
        [InlineKeyboardButton(
            text=f"✅ Confirmer ({fmt_money(final_price)})",
            callback_data=f"shop:confirm_qty:{product_id}:{qty}:{reduction}"
        )],
        [InlineKeyboardButton(text="❌ Annuler", callback_data="shop:cancel")],
    ]
    await message.answer(
        f"✅ Code promo appliqué ! Réduction : -{fmt_money(reduction)}\n"
        f"Total à payer : <b>{fmt_money(final_price)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "shop:cancel")
async def cancel_purchase(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Achat annulé.")
    await callback.answer()


# ── Achat effectif ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("shop:confirm_qty:"))
async def do_purchase(callback: CallbackQuery, state: FSMContext, labels: dict) -> None:
    parts = callback.data.split(":")
    product_id = int(parts[2])
    qty = int(parts[3])
    reduction = int(parts[4])
    buyer_id = callback.from_user.id

    state_data = await state.get_data()
    promo_code_str = state_data.get("promo_code")

    key = (buyer_id, product_id)
    if key in _purchases_in_progress:
        await callback.answer("Achat en cours, patientez…", show_alert=True)
        return
    _purchases_in_progress.add(key)

    try:
        await _process_purchase(
            callback, product_id, qty, buyer_id, reduction, promo_code_str, labels
        )
    finally:
        _purchases_in_progress.discard(key)
        await state.clear()


async def _process_purchase(callback: CallbackQuery, product_id: int, qty: int,
                             buyer_id: int, reduction: int, promo_code_str: str | None,
                             labels: dict) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, buyer_id,
            callback.from_user.username, callback.from_user.full_name,
        )
        product = await session.get(Product, product_id)
        if not product or product.status != ProductStatus.PUBLISHED:
            await callback.answer("Produit indisponible.", show_alert=True)
            return

        total_price = product.price_cents * qty - reduction
        total_price = max(0, total_price)

        # Vérifier le stock AVANT de démarrer
        available = await stock.count_available(session, product_id)
        if available < qty:
            out_msg = await get_message(session, "out_of_stock")
            await callback.message.edit_text(
                f"⚠️ Stock insuffisant. Disponible : {available}. {out_msg}"
            )
            await callback.answer()
            return

        # Réserver toutes les unités (séquentiellement)
        reserved_units: list[ProductStockUnit] = []
        for _ in range(qty):
            unit = await stock.reserve_unit(session, product_id, buyer_id)
            if unit is None:
                # Rupture pendant la réservation — libérer celles déjà prises
                for u in reserved_units:
                    await stock.release_unit(session, u)
                out_msg = await get_message(session, "out_of_stock")
                await callback.message.edit_text(out_msg)
                await callback.answer()
                return
            reserved_units.append(unit)

        # Créer la commande principale (première unité)
        from db.models import Order as OrderModel
        order = OrderModel(
            user_id=user.id,
            product_id=product.id,
            price_cents=total_price,
            quantity=qty,
            status=OrderStatus.PENDING,
            promo_code=promo_code_str,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        # Débiter le portefeuille
        try:
            await debit(
                session, user.id, total_price, WalletTxType.PURCHASE,
                note=f"Achat {qty}x {product.name}",
            )
        except InsufficientBalance:
            for u in reserved_units:
                await stock.release_unit(session, u)
            order.status = OrderStatus.FAILED
            order.error_note = "Solde insuffisant"
            await session.commit()
            insuf_msg = await get_message(session, "purchase_insufficient")
            await callback.message.edit_text(insuf_msg)
            await callback.answer()
            return

        order.status = OrderStatus.PAID
        await session.commit()

        # Enregistrer l'utilisation du code promo
        if promo_code_str:
            from services.promo import validate_and_apply as vaa, record_use as ru
            try:
                _, promo_obj = await vaa(session, promo_code_str, user.id,
                                         product.price_cents * qty)
                await ru(session, promo_obj, user.id, order.id)
            except PromoError:
                pass  # Le code a peut-être déjà été enregistré

        # Livrer toutes les unités
        all_ok = True
        for i, unit in enumerate(reserved_units):
            ok = await delivery.deliver(
                callback.bot, session, order, unit, buyer_id
            )
            if not ok:
                all_ok = False

        if all_ok:
            # Gagner des points de fidélité
            points = await loyalty.earn_points(session, user.id, total_price)
            success_msg = await get_message(
                session, "purchase_success", product_name=product.name
            )
            if points > 0:
                success_msg += f"\n\n⭐ Vous avez gagné {points} point(s) de fidélité !"
            await callback.message.edit_text(success_msg)

            await notify.notify_admins(
                callback.bot, session, "sale",
                f"💰 Vente : {qty}x {product.name} — "
                f"{fmt_money(total_price)} — "
                f"@{callback.from_user.username or buyer_id}",
            )
        else:
            # Remboursement automatique
            await credit(
                session, user.id, total_price, WalletTxType.REFUND,
                note=f"Remboursement échec livraison commande #{order.id}",
            )
            refund_msg = await get_message(
                session, "purchase_refunded", amount=fmt_money(total_price)
            )
            await callback.message.edit_text(refund_msg)

    await callback.answer()


# ── Recherche produit ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "shop:search")
async def start_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchFlow.waiting_query)
    await callback.message.answer(
        "🔎 <b>Recherche</b>\n\n"
        "Envoyez :\n"
        "• Les 6 premiers chiffres d'un code (ex: <code>512346</code>)\n"
        "• Un mot-clé exact (ex: <code>Crédit Agricole</code>)\n\n"
        "Les résultats afficheront les articles disponibles."
    )
    await callback.answer()


@router.message(SearchFlow.waiting_query)
async def process_search(message: Message, state: FSMContext, labels: dict) -> None:
    query = message.text.strip()
    await state.clear()

    async with get_session() as session:
        import re
        # Détecter si c'est un code série (6 chiffres)
        if re.match(r"^\d{6}$", query):
            units = await stock.search_by_series(session, query)
            search_type = "série"
        else:
            units = await stock.search_by_keyword(session, query)
            search_type = "mot-clé"

        if not units:
            await message.answer(
                f"❌ Aucun article disponible pour « {query} »."
            )
            return

        # Grouper par produit
        product_ids = list(dict.fromkeys(u.product_id for u in units))
        results = []
        for pid in product_ids:
            prod = await session.get(Product, pid)
            prod_units = [u for u in units if u.product_id == pid]
            results.append((prod, len(prod_units)))

        lines = [f"🔎 Résultats pour « {query} » ({search_type}) :\n"]
        for prod, count in results:
            lines.append(
                f"📦 <b>{prod.name}</b> — {count} disponible(s) "
                f"— {fmt_money(prod.price_cents)}/unité"
            )

        await message.answer(
            "\n".join(lines),
            reply_markup=search_result_kb(results, labels),
        )


# ── Historique achats + re-livraison ─────────────────────────────────────────

@router.message(MatchesLabel("menu_purchases"))
async def show_purchases(message: Message) -> None:
    async with get_session() as session:
        user = await get_or_create_user(
            session, message.from_user.id,
            message.from_user.username, message.from_user.full_name,
        )
        result = await session.execute(
            select(Order, Product)
            .join(Product, Order.product_id == Product.id)
            .where(
                Order.user_id == user.id,
                Order.status == OrderStatus.DELIVERED,
            )
            .order_by(Order.delivered_at.desc())
            .limit(20)
        )
        rows = list(result.all())

    if not rows:
        await message.answer("Vous n'avez encore effectué aucun achat.")
        return

    from utils.formatting import fmt_datetime
    lines = ["🛒 <b>Mes achats</b>\n"]
    redeliver_rows = []
    for order, product in rows:
        lines.append(
            f"• {fmt_datetime(order.delivered_at)} — "
            f"{order.quantity}x {product.name} — "
            f"{fmt_money(order.price_cents)}"
        )
        if order.stock_unit_id:
            redeliver_rows.append((order, product))

    kb_rows = []
    for order, product in redeliver_rows[:5]:  # Max 5 boutons re-livraison
        kb_rows.append([InlineKeyboardButton(
            text=f"🔄 Re-recevoir : {product.name[:25]}",
            callback_data=f"shop:redeliver:{order.id}",
        )])

    await message.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None,
    )


@router.callback_query(F.data.startswith("shop:redeliver:"))
async def redeliver_file(callback: CallbackQuery) -> None:
    order_id = int(callback.data.split(":")[2])
    async with get_session() as session:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.username, callback.from_user.full_name,
        )
        order = await session.get(Order, order_id)
        if not order or order.user_id != user.id:
            await callback.answer("Commande introuvable.", show_alert=True)
            return

        ok = await delivery.redeliver(
            callback.bot, session, order, callback.from_user.id
        )

    if ok:
        await callback.answer("✅ Fichier renvoyé !", show_alert=True)
    else:
        await callback.answer(
            "❌ Impossible de renvoyer ce fichier. Contactez le support.",
            show_alert=True,
        )
