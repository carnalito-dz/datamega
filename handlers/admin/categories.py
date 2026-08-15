from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import Category
from db.session import get_session
from keyboards.admin_kb import categories_admin_kb, category_detail_kb
from services.journal import log_action
from utils.filters import IsAdmin
from utils.states import CategoryFlow

router = Router(name="admin_categories")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


async def _all_categories(session) -> list[Category]:
    result = await session.execute(select(Category).order_by(Category.position))
    return list(result.scalars().all())


@router.callback_query(F.data == "admin:categories")
async def list_categories(callback: CallbackQuery, labels: dict[str, str]) -> None:
    async with get_session() as session:
        cats = await _all_categories(session)
    await callback.message.edit_text(
        "📂 <b>Catégories</b>\n\nSélectionnez une catégorie ou ajoutez-en une :",
        reply_markup=categories_admin_kb(cats, labels),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:cat:view:"))
async def view_category(callback: CallbackQuery, labels: dict[str, str]) -> None:
    cat_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        cat = await session.get(Category, cat_id)
    if not cat:
        await callback.answer("Catégorie introuvable.", show_alert=True)
        return
    status = "Active" if cat.is_active else "Désactivée"
    await callback.message.edit_text(
        f"📂 <b>{cat.name}</b>\nStatut : {status}\nPosition : {cat.position}",
        reply_markup=category_detail_kb(cat, labels),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:cat:add")
async def start_add_category(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CategoryFlow.adding_name)
    await callback.message.answer("Envoyez le nom de la nouvelle catégorie :")
    await callback.answer()


@router.message(CategoryFlow.adding_name)
async def receive_new_category_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("Nom invalide, réessayez.")
        return
    async with get_session() as session:
        max_pos = await session.execute(select(Category.position).order_by(Category.position.desc()).limit(1))
        last = max_pos.scalar_one_or_none() or 0
        cat = Category(name=name, position=last + 1, is_active=True)
        session.add(cat)
        await session.commit()
        await log_action(session, message.from_user.id, "categorie_creee", name)
    await state.clear()
    await message.answer(f"✅ Catégorie « {name} » créée.")


@router.callback_query(F.data.startswith("admin:cat:rename:"))
async def start_rename_category(callback: CallbackQuery, state: FSMContext) -> None:
    cat_id = int(callback.data.split(":")[3])
    await state.set_state(CategoryFlow.editing_name)
    await state.update_data(category_id=cat_id)
    await callback.message.answer("Envoyez le nouveau nom de la catégorie :")
    await callback.answer()


@router.message(CategoryFlow.editing_name)
async def receive_rename_category(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cat_id = data["category_id"]
    new_name = message.text.strip()
    async with get_session() as session:
        cat = await session.get(Category, cat_id)
        if not cat:
            await message.answer("Catégorie introuvable.")
            await state.clear()
            return
        old_name = cat.name
        cat.name = new_name
        await session.commit()
        await log_action(session, message.from_user.id, "categorie_renommee", f"{old_name} -> {new_name}")
    await state.clear()
    await message.answer(f"✅ Catégorie renommée en « {new_name} ».")


@router.callback_query(F.data.startswith("admin:cat:toggle:"))
async def toggle_category(callback: CallbackQuery, labels: dict[str, str]) -> None:
    cat_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        cat = await session.get(Category, cat_id)
        if not cat:
            await callback.answer("Introuvable.", show_alert=True)
            return
        cat.is_active = not cat.is_active
        await session.commit()
        await log_action(session, callback.from_user.id,
                          "categorie_toggle", f"{cat.name} -> active={cat.is_active}")
        status = "réactivée" if cat.is_active else "désactivée"
        await callback.message.edit_text(
            f"📂 <b>{cat.name}</b>\nCatégorie {status}.",
            reply_markup=category_detail_kb(cat, labels),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:cat:up:"))
async def move_category_up(callback: CallbackQuery, labels: dict[str, str]) -> None:
    await _move_category(callback, -1, labels)


@router.callback_query(F.data.startswith("admin:cat:down:"))
async def move_category_down(callback: CallbackQuery, labels: dict[str, str]) -> None:
    await _move_category(callback, 1, labels)


async def _move_category(callback: CallbackQuery, direction: int, labels: dict[str, str]) -> None:
    cat_id = int(callback.data.split(":")[3])
    async with get_session() as session:
        cats = await _all_categories(session)
        idx = next((i for i, c in enumerate(cats) if c.id == cat_id), None)
        if idx is None:
            await callback.answer("Introuvable.", show_alert=True)
            return
        swap_idx = idx + direction
        if 0 <= swap_idx < len(cats):
            cats[idx].position, cats[swap_idx].position = cats[swap_idx].position, cats[idx].position
            await session.commit()
        cat = await session.get(Category, cat_id)
    await callback.message.edit_text(
        f"📂 <b>{cat.name}</b>\nOrdre mis à jour.", reply_markup=category_detail_kb(cat, labels)
    )
    await callback.answer()
