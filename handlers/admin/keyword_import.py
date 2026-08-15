"""
Import de mots-clés en masse depuis un fichier CSV ou texte.

Format accepté (2 colonnes, séparateur virgule ou point-virgule) :
  produit_id,mot_clé
  512,Crédit Agricole
  512,banque
  513,PSG
  513,football

Ou avec le nom du produit à la place de l'ID :
  Crédit Agricole Story,banque menace
  Crédit Agricole Story,fermeture

Le bot tente de matcher le nom par recherche insensible à la casse.
Lignes invalides ou produits introuvables sont signalés dans le rapport.
"""
from __future__ import annotations

import csv
import io

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Document, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func

from db.models import Product, ProductKeyword
from db.session import get_session
from services.journal import log_action
from utils.filters import IsAdmin
from utils.states import KeywordImportFlow

router = Router(name="admin_keyword_import")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin:keywords:import")
async def start_import(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(KeywordImportFlow.waiting_file)
    await callback.message.answer(
        "📥 <b>Import de mots-clés en masse</b>\n\n"
        "Envoyez un fichier <b>.csv</b> ou <b>.txt</b> avec le format suivant "
        "(séparateur : virgule ou point-virgule) :\n\n"
        "<code>produit_id,mot_clé</code>\n"
        "ou\n"
        "<code>nom_du_produit,mot_clé</code>\n\n"
        "Exemples :\n"
        "<code>512,Crédit Agricole\n"
        "512,banque\n"
        "513,PSG\n"
        "Mon Produit,football</code>\n\n"
        "Envoyez /annuler pour abandonner."
    )
    await callback.answer()


@router.message(KeywordImportFlow.waiting_file, F.text == "/annuler")
async def cancel_import(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Import annulé.")


@router.message(KeywordImportFlow.waiting_file, F.document)
async def receive_import_file(message: Message, state: FSMContext) -> None:
    doc: Document = message.document
    if not doc.file_name or not doc.file_name.lower().endswith((".csv", ".txt")):
        await message.answer("❌ Format non supporté. Envoyez un fichier .csv ou .txt")
        return

    await state.clear()
    await message.answer("⏳ Traitement en cours…")

    # Télécharger le fichier
    file = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    raw = file_bytes.read().decode("utf-8-sig", errors="replace")

    # Parser
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Détecter séparateur
        sep = ";" if ";" in line else ","
        parts = line.split(sep, maxsplit=1)
        if len(parts) == 2:
            rows.append((parts[0].strip(), parts[1].strip()))

    if not rows:
        await message.answer("❌ Aucune ligne valide détectée dans le fichier.")
        return

    # Traiter
    added_total = 0
    skipped_total = 0
    not_found = []
    errors = []

    async with get_session() as session:
        # Cache produits (id et nom)
        all_products_r = await session.execute(select(Product))
        all_products = list(all_products_r.scalars().all())
        prod_by_id = {str(p.id): p for p in all_products}
        prod_by_name = {p.name.lower(): p for p in all_products}

        for ref, keyword in rows:
            if not keyword or len(keyword) > 100:
                errors.append(f"Mot-clé invalide : « {keyword[:30]} »")
                skipped_total += 1
                continue

            # Résoudre le produit
            product = prod_by_id.get(ref)
            if product is None:
                product = prod_by_name.get(ref.lower())
            if product is None:
                if ref not in not_found:
                    not_found.append(ref)
                skipped_total += 1
                continue

            # Vérifier doublon
            existing = await session.execute(
                select(ProductKeyword).where(
                    ProductKeyword.product_id == product.id,
                    ProductKeyword.keyword == keyword,
                )
            )
            if existing.scalar_one_or_none():
                skipped_total += 1
                continue

            session.add(ProductKeyword(product_id=product.id, keyword=keyword))
            added_total += 1

        await session.commit()
        await log_action(
            session, message.from_user.id, "keywords_import_masse",
            f"ajoutés={added_total} ignorés={skipped_total}"
        )

    # Rapport
    lines_report = [
        f"✅ <b>Import terminé</b>\n",
        f"• Mots-clés ajoutés : <b>{added_total}</b>",
        f"• Ignorés (doublons/invalides) : {skipped_total}",
    ]
    if not_found:
        lines_report.append(f"• Produits introuvables : {', '.join(not_found[:10])}")
    if errors:
        lines_report.append(f"• Erreurs : {'; '.join(errors[:5])}")

    await message.answer("\n".join(lines_report))


@router.message(KeywordImportFlow.waiting_file)
async def import_wrong_type(message: Message) -> None:
    await message.answer("Envoyez un fichier .csv ou .txt, ou /annuler.")
