"""Tous les états FSM (aiogram StatesGroup) — DATA MEGA V3 complet."""
from aiogram.fsm.state import State, StatesGroup


# ── Client ──────────────────────────────────────────────────────────────────

class DepositFlow(StatesGroup):
    choosing_amount        = State()
    choosing_custom_amount = State()
    choosing_currency      = State()

class SupportFlow(StatesGroup):
    writing_message = State()

class SearchFlow(StatesGroup):
    waiting_query = State()

class PromoFlow(StatesGroup):
    entering_code = State()

class QuantityFlow(StatesGroup):
    choosing_quantity = State()


# ── Admin : catégories ───────────────────────────────────────────────────────

class CategoryFlow(StatesGroup):
    adding_name  = State()
    editing_name = State()


# ── Admin : produits ─────────────────────────────────────────────────────────

class ProductFlow(StatesGroup):
    adding_name        = State()
    adding_description = State()
    adding_price       = State()
    choosing_category  = State()
    adding_image       = State()
    adding_files       = State()
    adding_keywords    = State()  # étape optionnelle après le stock
    editing_field      = State()
    editing_value      = State()
    searching          = State()


# ── Admin : restock ──────────────────────────────────────────────────────────

class RestockFlow(StatesGroup):
    sending_files = State()


# ── Admin : mots-clés produit ────────────────────────────────────────────────

class KeywordFlow(StatesGroup):
    adding_keyword = State()


# ── Admin : clients ──────────────────────────────────────────────────────────

class ClientWalletFlow(StatesGroup):
    choosing_amount = State()
    choosing_note   = State()

class ClientSearchFlow(StatesGroup):
    waiting_query = State()

class ClientLoyaltyFlow(StatesGroup):
    choosing_delta = State()
    choosing_note  = State()


# ── Admin : messagerie support ───────────────────────────────────────────────

class AdminReplyFlow(StatesGroup):
    choosing_user    = State()
    writing_reply    = State()


# ── Admin : broadcast ────────────────────────────────────────────────────────

class BroadcastFlow(StatesGroup):
    writing_message = State()
    confirming      = State()


# ── Admin : codes promo ──────────────────────────────────────────────────────

class PromoAdminFlow(StatesGroup):
    entering_code      = State()
    choosing_type      = State()
    entering_value     = State()
    entering_max_uses  = State()
    entering_expiry    = State()


# ── Admin : paramètres ───────────────────────────────────────────────────────

class SettingsFlow(StatesGroup):
    editing_value  = State()
    admin_add      = State()
    admin_remove   = State()


# ── Admin : libellés ─────────────────────────────────────────────────────────

class LabelFlow(StatesGroup):
    editing_value = State()


# ── Admin : import mots-clés en masse ────────────────────────────────────────

class KeywordImportFlow(StatesGroup):
    waiting_file = State()
