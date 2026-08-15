"""
Panel 🏷 Libellés : renommer n'importe quel bouton du bot (client + admin)
directement depuis Telegram. Voir services/labels.py pour le registre
complet et le principe de fonctionnement.
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.admin_kb import label_detail_kb, labels_in_section_kb, labels_sections_kb
from services import labels as labels_service
from services.journal import log_action
from utils.filters import IsAdmin
from utils.states import LabelFlow

router = Router(name="admin_labels")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:labels")
async def show_sections(callback: CallbackQuery, labels: dict[str, str]) -> None:
    await callback.message.edit_text(
        "🏷 <b>Libellés des boutons</b>\n\n"
        "Choisissez une section pour renommer les boutons correspondants :",
        reply_markup=labels_sections_kb(labels_service.SECTIONS, labels),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:label:section:"))
async def show_section(callback: CallbackQuery, labels: dict[str, str]) -> None:
    idx = int(callback.data.split(":")[3])
    if not (0 <= idx < len(labels_service.SECTIONS)):
        await callback.answer("Section introuvable.", show_alert=True)
        return
    section = labels_service.SECTIONS[idx]
    entries = labels_service.labels_in_section(section)

    lines = [f"🏷 <b>{section}</b>\n"]
    for lb in entries:
        lines.append(f"• <code>{lb.key}</code> : {labels[lb.key]}")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=labels_in_section_kb(idx, [lb.key for lb in entries], labels),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:label:edit:"))
async def start_edit_label(callback: CallbackQuery, state: FSMContext, labels: dict[str, str]) -> None:
    key = callback.data.split(":", 3)[3]
    definition = labels_service.get_definition(key)
    if definition is None:
        await callback.answer("Libellé introuvable.", show_alert=True)
        return

    await state.update_data(label_key=key)
    await state.set_state(LabelFlow.editing_value)
    await callback.message.answer(
        f"✏️ Libellé <code>{key}</code>\n\n"
        f"Valeur actuelle : {labels[key]}\n"
        f"Valeur par défaut : {definition.default}\n\n"
        f"Envoyez le nouveau texte du bouton :",
        reply_markup=label_detail_kb(key),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:label:reset:"))
async def reset_label(callback: CallbackQuery, labels: dict[str, str]) -> None:
    key = callback.data.split(":", 3)[3]
    definition = labels_service.get_definition(key)
    if definition is None:
        await callback.answer("Libellé introuvable.", show_alert=True)
        return

    from db.session import get_session
    async with get_session() as session:
        default_text = await labels_service.reset_label(session, key)
        await log_action(session, callback.from_user.id, "libelle_reinitialise", key)

    await callback.answer(f"Réinitialisé : {default_text}", show_alert=True)


@router.message(LabelFlow.editing_value)
async def receive_label_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key = data.get("label_key")
    definition = labels_service.get_definition(key)
    if definition is None:
        await message.answer("Session expirée, recommencez depuis le menu 🏷 Libellés.")
        await state.clear()
        return

    from db.session import get_session
    async with get_session() as session:
        try:
            normalized = await labels_service.set_label(session, key, message.text)
        except ValueError as exc:
            await message.answer(f"❌ {exc}\nRéessayez.")
            return
        await log_action(session, message.from_user.id, "libelle_modifie", f"{key} -> {normalized}")

    await state.clear()
    await message.answer(f"✅ Bouton mis à jour : <code>{key}</code> → {normalized}")
