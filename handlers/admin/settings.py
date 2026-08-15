"""
Panel ⚙️ Paramètres — version complète :
  • Réglages généraux (identité, boutique, dépôts)
  • Messages configurables
  • Gestion des admins (ajout/suppression)
  • Réinitialisation du bot
"""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

from db.session import get_session
from services import settings as settings_service
from services import messages as messages_service
from services.journal import log_action
from utils.filters import IsAdmin
from utils.states import SettingsFlow

router = Router(name="admin_settings")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ------------------------------------------------------------------ #
# Menu principal des paramètres
# ------------------------------------------------------------------ #

def _settings_main_kb(labels: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Réglages généraux",  callback_data="admin:settings:general")],
        [InlineKeyboardButton(text="💬 Messages du bot",     callback_data="admin:settings:messages")],
        [InlineKeyboardButton(text="👑 Gestion des admins",  callback_data="admin:settings:admins")],
        [InlineKeyboardButton(text="🔴 Réinitialiser le bot", callback_data="admin:settings:reset_confirm")],
        [InlineKeyboardButton(text=labels.get("admin_back_home", "⬅️ Menu admin"), callback_data="admin:home")],
    ])


@router.callback_query(F.data == "admin:settings")
async def show_settings_menu(callback: CallbackQuery, labels: dict[str, str]) -> None:
    await callback.message.edit_text(
        "⚙️ <b>Paramètres</b>\n\nChoisissez une section :",
        reply_markup=_settings_main_kb(labels),
    )
    await callback.answer()


# ------------------------------------------------------------------ #
# Réglages généraux — par section
# ------------------------------------------------------------------ #

def _section_kb(section: str, labels: dict[str, str]) -> InlineKeyboardMarkup:
    defs = settings_service.settings_in_section(section)
    rows = [
        [InlineKeyboardButton(text=f"✏️ {d.label}", callback_data=f"admin:setting:edit:{d.key}")]
        for d in defs
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Paramètres", callback_data="admin:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin:settings:general")
async def show_general_settings(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        values = await settings_service.get_all_raw(session)

    sections = settings_service.SECTIONS
    lines = ["⚙️ <b>Réglages généraux</b>\n"]
    for section in sections:
        lines.append(f"\n<b>{section}</b>")
        for s in settings_service.settings_in_section(section):
            lines.append(f"• {s.label} : <code>{values[s.key]}</code>")

    # Clavier avec toutes les sections
    rows = [
        [InlineKeyboardButton(text=f"📁 {sec}", callback_data=f"admin:settings:section:{i}")]
        for i, sec in enumerate(sections)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Paramètres", callback_data="admin:settings")])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:settings:section:"))
async def show_section(callback: CallbackQuery, labels: dict[str, str]) -> None:
    idx = int(callback.data.split(":")[-1])
    sections = settings_service.SECTIONS
    if not (0 <= idx < len(sections)):
        await callback.answer("Section introuvable.", show_alert=True)
        return
    section = sections[idx]
    async with get_session() as session:
        values = await settings_service.get_all_raw(session)

    defs = settings_service.settings_in_section(section)
    lines = [f"⚙️ <b>{section}</b>\n"]
    for d in defs:
        lines.append(f"• <b>{d.label}</b>\n  {d.help_text}\n  Valeur : <code>{values[d.key]}</code>\n")

    rows = [
        [InlineKeyboardButton(text=f"✏️ {d.label}", callback_data=f"admin:setting:edit:{d.key}")]
        for d in defs
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Réglages", callback_data="admin:settings:general")])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:setting:edit:"))
async def start_edit_setting(callback: CallbackQuery, state: FSMContext, labels: dict[str, str]) -> None:
    key = callback.data.split(":", 3)[3]
    definition = settings_service.get_definition(key)
    if definition is None:
        await callback.answer("Réglage introuvable.", show_alert=True)
        return
    async with get_session() as session:
        current = await settings_service.get_raw(session, key)

    await state.update_data(setting_key=key, setting_type="general")
    await state.set_state(SettingsFlow.editing_value)
    await callback.message.answer(
        f"✏️ <b>{definition.label}</b>\n\n"
        f"{definition.help_text}\n\n"
        f"Valeur actuelle : <code>{current}</code>\n\n"
        f"Envoyez la nouvelle valeur (ou /annuler) :",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Annuler", callback_data="admin:settings:general")]
        ]),
    )
    await callback.answer()


@router.message(SettingsFlow.editing_value, F.text == "/annuler")
async def cancel_edit_setting(message: Message, state: FSMContext, labels: dict[str, str]) -> None:
    await state.clear()
    await message.answer("Modification annulée.")


@router.message(SettingsFlow.editing_value)
async def receive_setting_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key = data.get("setting_key")
    setting_type = data.get("setting_type", "general")

    if setting_type == "message":
        # Édition d'un message configurable
        definition = messages_service.get_definition(key)
        if not definition:
            await message.answer("Session expirée.")
            await state.clear()
            return
        async with get_session() as session:
            try:
                normalized = await messages_service.set_message(session, key, message.text)
            except ValueError as exc:
                await message.answer(f"❌ {exc}\nRéessayez ou /annuler.")
                return
            await log_action(session, message.from_user.id, "message_modifie", f"{key}")
        await state.clear()
        await message.answer(f"✅ Message mis à jour : <b>{definition.label}</b>")
        return

    # Réglage général
    definition = settings_service.get_definition(key)
    if not definition:
        await message.answer("Session expirée.")
        await state.clear()
        return
    async with get_session() as session:
        try:
            normalized = await settings_service.set_value(session, key, message.text)
        except settings_service.InvalidSettingValue as exc:
            await message.answer(f"❌ {exc}\nRéessayez ou /annuler.")
            return
        await log_action(session, message.from_user.id, "reglage_modifie", f"{key} -> {normalized}")
    await state.clear()
    await message.answer(f"✅ <b>{definition.label}</b> mis à jour : <code>{normalized}</code>")


# ------------------------------------------------------------------ #
# Messages configurables
# ------------------------------------------------------------------ #

def _messages_kb(section_idx: int, labels: dict[str, str]) -> InlineKeyboardMarkup:
    sections = messages_service.SECTIONS
    rows = [
        [InlineKeyboardButton(text=f"📁 {sec}", callback_data=f"admin:settings:msgsec:{i}")]
        for i, sec in enumerate(sections)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Paramètres", callback_data="admin:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin:settings:messages")
async def show_messages_menu(callback: CallbackQuery, labels: dict[str, str]) -> None:
    sections = messages_service.SECTIONS
    rows = [
        [InlineKeyboardButton(text=f"📁 {sec}", callback_data=f"admin:settings:msgsec:{i}")]
        for i, sec in enumerate(sections)
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Paramètres", callback_data="admin:settings")])
    await callback.message.edit_text(
        "💬 <b>Messages du bot</b>\n\nChoisissez une section :",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:settings:msgsec:"))
async def show_messages_section(callback: CallbackQuery, labels: dict[str, str]) -> None:
    idx = int(callback.data.split(":")[-1])
    sections = messages_service.SECTIONS
    if not (0 <= idx < len(sections)):
        await callback.answer("Section introuvable.", show_alert=True)
        return
    section = sections[idx]
    defs = messages_service.messages_in_section(section)

    async with get_session() as session:
        all_msgs = await messages_service.get_all_messages(session)

    lines = [f"💬 <b>{section}</b>\n"]
    for d in defs:
        preview = all_msgs[d.key][:80].replace("\n", " ")
        if d.variables:
            vars_str = ", ".join(d.variables)
            lines.append(f"• <b>{d.label}</b>\n  Variables : {vars_str}\n  <i>{preview}…</i>\n")
        else:
            lines.append(f"• <b>{d.label}</b>\n  <i>{preview}…</i>\n")

    rows = [
        [InlineKeyboardButton(text=f"✏️ {d.label}", callback_data=f"admin:msg:edit:{d.key}")]
        for d in defs
    ] + [
        [InlineKeyboardButton(text=f"🔄 Réinit. {d.label}", callback_data=f"admin:msg:reset:{d.key}")]
        for d in defs
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Messages", callback_data="admin:settings:messages")])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:msg:edit:"))
async def start_edit_message(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 3)[3]
    definition = messages_service.get_definition(key)
    if not definition:
        await callback.answer("Message introuvable.", show_alert=True)
        return
    async with get_session() as session:
        all_msgs = await messages_service.get_all_messages(session)
    current = all_msgs[key]
    vars_help = (
        f"\n\nVariables disponibles : {', '.join(definition.variables)}"
        if definition.variables else ""
    )
    await state.update_data(setting_key=key, setting_type="message")
    await state.set_state(SettingsFlow.editing_value)
    await callback.message.answer(
        f"✏️ <b>{definition.label}</b>{vars_help}\n\n"
        f"Texte actuel :\n<i>{current}</i>\n\n"
        f"Envoyez le nouveau texte (HTML supporté) ou /annuler :"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:msg:reset:"))
async def reset_message(callback: CallbackQuery) -> None:
    key = callback.data.split(":", 3)[3]
    definition = messages_service.get_definition(key)
    if not definition:
        await callback.answer("Message introuvable.", show_alert=True)
        return
    async with get_session() as session:
        default = await messages_service.reset_message(session, key)
        await log_action(session, callback.from_user.id, "message_reinitialise", key)
    await callback.answer(f"✅ Réinitialisé : {definition.label}", show_alert=True)


# ------------------------------------------------------------------ #
# Gestion des admins
# ------------------------------------------------------------------ #

@router.callback_query(F.data == "admin:settings:admins")
async def show_admins(callback: CallbackQuery, labels: dict[str, str]) -> None:
    import config as cfg
    async with get_session() as session:
        dynamic = await settings_service.get_dynamic_admin_ids(session)

    lines = ["👑 <b>Gestion des admins</b>\n"]
    lines.append("<b>Admins fixes (config.py, non supprimables)</b>")
    for aid in sorted(cfg.ADMIN_IDS):
        lines.append(f"  • <code>{aid}</code>")
    if dynamic:
        lines.append("\n<b>Admins ajoutés depuis le panel</b>")
        for aid in sorted(dynamic):
            lines.append(f"  • <code>{aid}</code>")
    else:
        lines.append("\nAucun admin ajouté depuis le panel.")

    rows = [
        [InlineKeyboardButton(text="➕ Ajouter un admin", callback_data="admin:settings:admin_add")],
        [InlineKeyboardButton(text="➖ Supprimer un admin", callback_data="admin:settings:admin_remove")],
        [InlineKeyboardButton(text="⬅️ Paramètres", callback_data="admin:settings")],
    ]
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:settings:admin_add")
async def start_add_admin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.admin_add)
    await callback.message.answer(
        "Envoyez l'<b>ID Telegram</b> du nouvel admin (entier, ex: <code>123456789</code>)\n"
        "ou /annuler :"
    )
    await callback.answer()


@router.message(SettingsFlow.admin_add)
async def receive_admin_add(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lstrip("/annuler")
    if message.text.strip() == "/annuler":
        await state.clear()
        await message.answer("Annulé.")
        return
    if not text.isdigit():
        await message.answer("ID invalide. Envoyez un entier ou /annuler.")
        return
    new_id = int(text)
    async with get_session() as session:
        await settings_service.add_admin(session, new_id)
        await log_action(session, message.from_user.id, "admin_ajoute", str(new_id))
    await state.clear()
    await message.answer(f"✅ Admin <code>{new_id}</code> ajouté.")


@router.callback_query(F.data == "admin:settings:admin_remove")
async def start_remove_admin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SettingsFlow.admin_remove)
    await callback.message.answer(
        "Envoyez l'<b>ID Telegram</b> de l'admin à supprimer\n"
        "(seuls les admins ajoutés depuis le panel peuvent être supprimés)\n"
        "ou /annuler :"
    )
    await callback.answer()


@router.message(SettingsFlow.admin_remove)
async def receive_admin_remove(message: Message, state: FSMContext) -> None:
    if message.text.strip() == "/annuler":
        await state.clear()
        await message.answer("Annulé.")
        return
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("ID invalide. Envoyez un entier ou /annuler.")
        return
    rm_id = int(text)
    async with get_session() as session:
        ok = await settings_service.remove_admin(session, rm_id)
        if not ok:
            await message.answer(
                f"❌ <code>{rm_id}</code> fait partie des admins fixes (config.py) "
                f"et ne peut pas être supprimé depuis le panel."
            )
            await state.clear()
            return
        await log_action(session, message.from_user.id, "admin_supprime", str(rm_id))
    await state.clear()
    await message.answer(f"✅ Admin <code>{rm_id}</code> supprimé.")


# ------------------------------------------------------------------ #
# Réinitialisation du bot
# ------------------------------------------------------------------ #

@router.callback_query(F.data == "admin:settings:reset_confirm")
async def reset_confirm(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🔴 <b>RÉINITIALISATION COMPLÈTE</b>\n\n"
        "⚠️ Cette action va <b>effacer définitivement</b> :\n"
        "• Tous les clients et leurs soldes\n"
        "• Tout le catalogue (catégories, produits, stock)\n"
        "• Toutes les commandes et dépôts\n"
        "• Tous les paramètres et libellés personnalisés\n"
        "• Tous les logs et notifications\n\n"
        "<b>Cette action est IRRÉVERSIBLE.</b>\n\n"
        "Confirmez-vous ?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔴 OUI, tout effacer", callback_data="admin:settings:reset_execute")],
            [InlineKeyboardButton(text="⬅️ Annuler", callback_data="admin:settings")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:settings:reset_execute")
async def reset_execute(callback: CallbackQuery) -> None:
    await callback.message.edit_text("⏳ Réinitialisation en cours…")
    async with get_session() as session:
        await settings_service.factory_reset(session)
    await callback.message.edit_text(
        "✅ <b>Bot réinitialisé.</b>\n\n"
        "Toutes les données ont été effacées. "
        "Le bot est prêt pour un nouveau départ."
    )
    await callback.answer()
