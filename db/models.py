"""
Modèles SQLAlchemy 2.0 — DATA MEGA V3 complet.

Tables :
    users, wallets, wallet_transactions,
    categories, products, product_stock, product_keywords,
    orders, deposits,
    support_messages,
    promo_codes, promo_uses,
    loyalty_points, referrals,
    admin_logs, notifications, settings
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Integer, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


# ──────────────────────────────────────────────────────────────────────────── #
# Enums
# ──────────────────────────────────────────────────────────────────────────── #

class ProductStatus(str, enum.Enum):
    DRAFT     = "draft"
    PUBLISHED = "published"
    DELETED   = "deleted"


class StockStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED  = "reserved"
    SOLD      = "sold"


class OrderStatus(str, enum.Enum):
    PENDING   = "pending"
    PAID      = "paid"
    DELIVERED = "delivered"
    FAILED    = "failed"
    REFUNDED  = "refunded"


class DepositStatus(str, enum.Enum):
    WAITING    = "waiting"
    CONFIRMING = "confirming"
    CONFIRMED  = "confirmed"
    FINISHED   = "finished"
    FAILED     = "failed"
    EXPIRED    = "expired"


class WalletTxType(str, enum.Enum):
    DEPOSIT      = "deposit"
    PURCHASE     = "purchase"
    REFUND       = "refund"
    BONUS        = "bonus"
    ADMIN_CREDIT = "admin_credit"
    ADMIN_DEBIT  = "admin_debit"
    PROMO        = "promo"
    REFERRAL     = "referral"


class SupportMessageDirection(str, enum.Enum):
    CLIENT_TO_ADMIN = "client_to_admin"
    ADMIN_TO_CLIENT = "admin_to_client"


# ──────────────────────────────────────────────────────────────────────────── #
# Users / Wallets
# ──────────────────────────────────────────────────────────────────────────── #

class User(Base):
    __tablename__ = "users"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    telegram_id: Mapped[int]      = mapped_column(BigInteger, unique=True, index=True)
    username:    Mapped[str|None] = mapped_column(String(255), nullable=True)
    full_name:   Mapped[str|None] = mapped_column(String(255), nullable=True)
    is_banned:   Mapped[bool]     = mapped_column(Boolean, default=False)
    # Code de parrainage propre à cet utilisateur (généré à l'inscription)
    referral_code: Mapped[str|None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    # ID de l'utilisateur qui l'a parrainé (nullable si pas de parrain)
    referred_by_id: Mapped[int|None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at:  Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    wallet:           Mapped["Wallet"]               = relationship(back_populates="user", uselist=False)
    orders:           Mapped[list["Order"]]           = relationship(back_populates="user")
    support_messages: Mapped[list["SupportMessage"]]  = relationship(back_populates="user", foreign_keys="SupportMessage.user_id")


class Wallet(Base):
    __tablename__ = "wallets"

    id:            Mapped[int] = mapped_column(primary_key=True)
    user_id:       Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    # Points de fidélité (entier, 1 point = défini par l'admin)
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="wallet")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id:                  Mapped[int]         = mapped_column(primary_key=True)
    user_id:             Mapped[int]         = mapped_column(ForeignKey("users.id"), index=True)
    type:                Mapped[WalletTxType] = mapped_column(Enum(WalletTxType))
    amount_cents:        Mapped[int]         = mapped_column(Integer)
    balance_after_cents: Mapped[int]         = mapped_column(Integer)
    note:                Mapped[str|None]    = mapped_column(String(500), nullable=True)
    created_at:          Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


# ──────────────────────────────────────────────────────────────────────────── #
# Catalogue
# ──────────────────────────────────────────────────────────────────────────── #

class Category(Base):
    __tablename__ = "categories"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    name:       Mapped[str]      = mapped_column(String(255))
    emoji:      Mapped[str|None] = mapped_column(String(16), nullable=True)
    position:   Mapped[int]      = mapped_column(Integer, default=0)
    is_active:  Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id:            Mapped[int]           = mapped_column(primary_key=True)
    category_id:   Mapped[int]           = mapped_column(ForeignKey("categories.id"))
    name:          Mapped[str]           = mapped_column(String(255))
    description:   Mapped[str|None]      = mapped_column(Text, nullable=True)
    price_cents:   Mapped[int]           = mapped_column(Integer)
    image_file_id: Mapped[str|None]      = mapped_column(String(500), nullable=True)
    status:        Mapped[ProductStatus] = mapped_column(Enum(ProductStatus), default=ProductStatus.DRAFT)
    position:      Mapped[int]           = mapped_column(Integer, default=0)
    created_at:    Mapped[dt.datetime]   = mapped_column(DateTime, default=utcnow)

    category:    Mapped["Category"]              = relationship(back_populates="products")
    stock_units: Mapped[list["ProductStockUnit"]] = relationship(back_populates="product")
    keywords:    Mapped[list["ProductKeyword"]]   = relationship(back_populates="product", cascade="all, delete-orphan")


class ProductStockUnit(Base):
    """Une unité de stock = un fichier Telegram OU un contenu texte."""
    __tablename__ = "product_stock"

    id:              Mapped[int]         = mapped_column(primary_key=True)
    product_id:      Mapped[int]         = mapped_column(ForeignKey("products.id"), index=True)
    telegram_file_id: Mapped[str]        = mapped_column(String(500), default="")
    file_name:       Mapped[str|None]    = mapped_column(String(500), nullable=True)
    text_content:    Mapped[str|None]    = mapped_column(Text, nullable=True)
    # Code série extrait automatiquement (6 premiers chiffres du text_content)
    series_code:     Mapped[str|None]    = mapped_column(String(16), nullable=True, index=True)
    status:          Mapped[StockStatus] = mapped_column(Enum(StockStatus), default=StockStatus.AVAILABLE, index=True)
    reserved_by:     Mapped[int|None]    = mapped_column(BigInteger, nullable=True)
    reserved_at:     Mapped[dt.datetime|None] = mapped_column(DateTime, nullable=True)
    sold_to:         Mapped[int|None]    = mapped_column(BigInteger, nullable=True)
    sold_at:         Mapped[dt.datetime|None] = mapped_column(DateTime, nullable=True)
    created_at:      Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    product: Mapped["Product"] = relationship(back_populates="stock_units")


class ProductKeyword(Base):
    """Mots-clés associés à un produit pour la recherche."""
    __tablename__ = "product_keywords"

    id:         Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    keyword:    Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    product: Mapped["Product"] = relationship(back_populates="keywords")

    __table_args__ = (
        UniqueConstraint("product_id", "keyword", name="uq_product_keyword"),
    )


# ──────────────────────────────────────────────────────────────────────────── #
# Commandes
# ──────────────────────────────────────────────────────────────────────────── #

class Order(Base):
    __tablename__ = "orders"

    id:           Mapped[int]         = mapped_column(primary_key=True)
    user_id:      Mapped[int]         = mapped_column(ForeignKey("users.id"), index=True)
    product_id:   Mapped[int]         = mapped_column(ForeignKey("products.id"))
    stock_unit_id: Mapped[int|None]   = mapped_column(ForeignKey("product_stock.id"), nullable=True)
    price_cents:  Mapped[int]         = mapped_column(Integer)
    # Quantité achetée (1 par défaut, peut être > 1)
    quantity:     Mapped[int]         = mapped_column(Integer, default=1)
    status:       Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    error_note:   Mapped[str|None]    = mapped_column(String(500), nullable=True)
    # Code promo utilisé (nullable)
    promo_code:   Mapped[str|None]    = mapped_column(String(64), nullable=True)
    created_at:   Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    delivered_at: Mapped[dt.datetime|None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")


# ──────────────────────────────────────────────────────────────────────────── #
# Dépôts crypto (NOWPayments)
# ──────────────────────────────────────────────────────────────────────────── #

class Deposit(Base):
    __tablename__ = "deposits"

    id:              Mapped[int]           = mapped_column(primary_key=True)
    user_id:         Mapped[int]           = mapped_column(ForeignKey("users.id"), index=True)
    payment_id:      Mapped[str]           = mapped_column(String(255), unique=True, index=True)
    currency:        Mapped[str]           = mapped_column(String(32))
    amount_usd_cents: Mapped[int]          = mapped_column(Integer)
    pay_amount:      Mapped[str|None]      = mapped_column(String(64), nullable=True)
    pay_address:     Mapped[str|None]      = mapped_column(String(255), nullable=True)
    status:          Mapped[DepositStatus] = mapped_column(Enum(DepositStatus), default=DepositStatus.WAITING)
    credited:        Mapped[bool]          = mapped_column(Boolean, default=False)
    created_at:      Mapped[dt.datetime]   = mapped_column(DateTime, default=utcnow)
    updated_at:      Mapped[dt.datetime]   = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ──────────────────────────────────────────────────────────────────────────── #
# Messagerie support admin ↔ client
# ──────────────────────────────────────────────────────────────────────────── #

class SupportMessage(Base):
    """Message dans le fil de support entre un client et les admins."""
    __tablename__ = "support_messages"

    id:          Mapped[int]                      = mapped_column(primary_key=True)
    user_id:     Mapped[int]                      = mapped_column(ForeignKey("users.id"), index=True)
    direction:   Mapped[SupportMessageDirection]  = mapped_column(Enum(SupportMessageDirection))
    # ID Telegram de l'admin qui a répondu (null si message client)
    admin_telegram_id: Mapped[int|None]           = mapped_column(BigInteger, nullable=True)
    text:        Mapped[str]                      = mapped_column(Text)
    is_read:     Mapped[bool]                     = mapped_column(Boolean, default=False)
    created_at:  Mapped[dt.datetime]              = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="support_messages", foreign_keys=[user_id])


# ──────────────────────────────────────────────────────────────────────────── #
# Codes promo
# ──────────────────────────────────────────────────────────────────────────── #

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    code:        Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    # Type : "percent" (réduction %) ou "fixed" (montant fixe en centimes)
    type:        Mapped[str]      = mapped_column(String(16))
    value:       Mapped[int]      = mapped_column(Integer)   # % ou centimes
    # Nombre max d'utilisations (0 = illimité)
    max_uses:    Mapped[int]      = mapped_column(Integer, default=0)
    uses_count:  Mapped[int]      = mapped_column(Integer, default=0)
    # Date d'expiration (null = pas d'expiration)
    expires_at:  Mapped[dt.datetime|None] = mapped_column(DateTime, nullable=True)
    is_active:   Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:  Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    uses: Mapped[list["PromoUse"]] = relationship(back_populates="promo")


class PromoUse(Base):
    """Trace chaque utilisation d'un code promo."""
    __tablename__ = "promo_uses"

    id:         Mapped[int] = mapped_column(primary_key=True)
    promo_id:   Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    user_id:    Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id:   Mapped[int|None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    used_at:    Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    promo: Mapped["PromoCode"] = relationship(back_populates="uses")

    __table_args__ = (
        UniqueConstraint("promo_id", "user_id", name="uq_promo_user"),
    )


# ──────────────────────────────────────────────────────────────────────────── #
# Journal / Notifications
# ──────────────────────────────────────────────────────────────────────────── #

class AdminLog(Base):
    __tablename__ = "admin_logs"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    admin_id:   Mapped[int|None] = mapped_column(BigInteger, nullable=True)
    action:     Mapped[str]      = mapped_column(String(255))
    details:    Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id:         Mapped[int]  = mapped_column(primary_key=True)
    type:       Mapped[str]  = mapped_column(String(64))
    message:    Mapped[str]  = mapped_column(Text)
    is_read:    Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    """Table clé/valeur pour tous les paramètres configurables."""
    __tablename__ = "settings"

    key:   Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("key"),)
