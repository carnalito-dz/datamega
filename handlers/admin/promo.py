"""Panel admin — Codes promo."""
from __future__ import annotations

import datetime as dt

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery, Message,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from db.session import get_session
from services import promo as promo_service
from services.journal import log_action
from utils.filters import IsAdmin
from utils.formatting import fmt_money
from utils.states import PromoAdminFlow

router = Router(name="admin_promo")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _back_kb(labels: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=labels.get("admin_back_home", "⬅️ Menu admin"),
            callback_data="admin:home",
        )]
    ])


@router.callback_query(F.data == "admin:promo")
async def show_promos(callback: CallbackQuery, labels: dict) -> None:
    async with get_session() as session:
        promos = await promo_service.list_promos(session)

    lines = ["🎟 <b>Codes promo</b>\n"]
    rows = []
    for p in promos:
        status = "✅" if p.is_active else "🚫"
        type_label = f"{p.value}%" if p.type == "percent" else fmt_money(p.value)
        expiry = f" (exp: {p.expires_at.strftime('%d/%m/%y')})" if p.expires_at else ""
        uses = f"{p.uses_count}/{p.max_uses}" if p.max_uses else f"{p.uses_count}/∞"
        lines.append(
            f"{status} <code>{p.code}</code> — {type_label} — {uses} utilisations{expiry}"
        )
        rows.append([
            InlineKeyboardButton(
                text=f"{'🟢' if p.is_active else '🔴'} {p.code}",
                callback_data=f"admin:promo:toggle:{p.id}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"admin:promo:delete:{p.id}",
            ),
        ])

    rows.append([InlineKeyboardButton(text="➕ Créer un code", callback_data="admin:promo:create")])
    rows.append([InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")])

    await callback.message.edit_text(
        "\n".join(lines) if len(lines) > 1 else "🎟 <b>Codes promo</b>\n\nAucun code créé.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:promo:create")
async def start_create_promo(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoAdminFlow.entering_code)
    await callback.message.answer(
        "Entrez le code promo (ex: BIENVENUE20)\n/annuler pour abandonner :"
    )
    await callback.answer()


@router.message(PromoAdminFlow.entering_code)
async def receive_promo_code(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/annuler":
        await state.clear()
        await message.answer("Annulé.")
        return
    code = message.text.strip().upper()
    if len(code) < 3 or len(code) > 32:
        await message.answer("Code invalide (3-32 caractères).")
        return
    await state.update_data(code=code)
    await state.set_state(PromoAdminFlow.choosing_type)
    await message.answer(
        "Type de réduction ?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="% Pourcentage", callback_data="promo_type:percent")],
            [InlineKeyboardButton(text="$ Montant fixe", callback_data="promo_type:fixed")],
        ]),
    )


@router.callback_query(PromoAdminFlow.choosing_type, F.data.startswith("promo_type:"))
async def receive_promo_type(callback: CallbackQuery, state: FSMContext) -> None:
    type_ = callback.data.split(":")[1]
    await state.update_data(type=type_)
    await state.set_state(PromoAdminFlow.entering_value)
    hint = "Entrez le pourcentage (ex: 20 pour -20%) :" if type_ == "percent" \
        else "Entrez le montant en USD (ex: 5 pour -5$) :"
    await callback.message.answer(hint)
    await callback.answer()


@router.message(PromoAdminFlow.entering_value)
async def receive_promo_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    type_ = data.get("type")
    try:
        if type_ == "percent":
            value = int(message.text.strip())
            if not 1 <= value <= 100:
                raise ValueError
        else:
            from utils.money import parse_usd_to_cents
            value = parse_usd_to_cents(message.text)
    except Exception:
        await message.answer("Valeur invalide, réessayez.")
        return
    await state.update_data(value=value)
    await state.set_state(PromoAdminFlow.entering_max_uses)
    await message.answer("Nombre max d'utilisations ? (0 = illimité) :")


@router.message(PromoAdminFlow.entering_max_uses)
async def receive_max_uses(message: Message, state: FSMContext) -> None:
    try:
        max_uses = int(message.text.strip())
        if max_uses < 0:
            raise ValueError
    except ValueError:
        await message.answer("Entrez un entier >= 0.")
        return
    await state.update_data(max_uses=max_uses)
    await state.set_state(PromoAdminFlow.entering_expiry)
    await message.answer(
        "Date d'expiration ? (format JJ/MM/AAAA ou « - » pour aucune expiration) :"
    )


@router.message(PromoAdminFlow.entering_expiry)
async def receive_expiry(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = message.text.strip()
    expires_at = None
    if text != "-":
        try:
            expires_at = dt.datetime.strptime(text, "%d/%m/%Y")
        except ValueError:
            await message.answer("Format invalide (JJ/MM/AAAA) ou « - ».")
            return

    async with get_session() as session:
        try:
            promo = await promo_service.create_promo(
                session,
                code=data["code"],
                type_=data["type"],
                value=data["value"],
                max_uses=data.get("max_uses", 0),
                expires_at=expires_at,
            )
        except Exception as e:
            await message.answer(f"❌ Erreur : {e}")
            await state.clear()
            return
        await log_action(
            session, message.from_user.id, "promo_cree", promo.code
        )

    await state.clear()
    type_label = f"{promo.value}%" if promo.type == "percent" else fmt_money(promo.value)
    await message.answer(
        f"✅ Code promo créé !\n"
        f"Code : <code>{promo.code}</code>\n"
        f"Réduction : {type_label}\n"
        f"Max utilisations : {promo.max_uses or 'illimité'}\n"
        f"Expiration : {expires_at.strftime('%d/%m/%Y') if expires_at else 'aucune'}"
    )


@router.callback_query(F.data.startswith("admin:promo:toggle:"))
async def toggle_promo(callback: CallbackQuery, labels: dict) -> None:
    promo_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        promo = await promo_service.toggle_promo(session, promo_id)
        if promo:
            await log_action(
                session, callback.from_user.id,
                "promo_toggle", f"{promo.code} -> {'actif' if promo.is_active else 'inactif'}"
            )
    await callback.answer("Statut modifié.", show_alert=True)
    await show_promos(callback, labels)


@router.callback_query(F.data.startswith("admin:promo:delete:"))
async def delete_promo(callback: CallbackQuery, labels: dict) -> None:
    promo_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        ok = await promo_service.delete_promo(session, promo_id)
        if ok:
            await log_action(session, callback.from_user.id, "promo_supprime", str(promo_id))
    await callback.answer("Code supprimé.", show_alert=True)
    await show_promos(callback, labels)
