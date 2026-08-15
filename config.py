"""
Configuration centrale de DATA MEGA V2.
Toutes les valeurs sensibles viennent des variables d'environnement.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


# --- Telegram ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_IDS: set[int] = _get_admin_ids()

# --- Base de données ---
# SQLite par défaut (avec volume Railway). Peut être remplacé par une URL
# PostgreSQL asyncpg (postgresql+asyncpg://...) sans changer le code.
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./data/datamega.db"
)

# --- NOWPayments ---
NOWPAYMENTS_API_KEY: str = os.getenv("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET: str = os.getenv("NOWPAYMENTS_IPN_SECRET", "")
NOWPAYMENTS_API_URL: str = "https://api.nowpayments.io/v1"

# Cryptos proposées pour le rechargement de solde
DEPOSIT_CURRENCIES: dict[str, str] = {
    "btc": "BTC",
    "eth": "ETH",
    "ltc": "LTC",
    "usdttrc20": "USDT (TRC20)",
    "usdtbsc": "USDT (BEP20)",
}

# Montants de dépôt proposés par défaut (USD)
DEPOSIT_PRESETS: list[int] = [10, 20, 50, 100]
MIN_DEPOSIT_USD: float = float(os.getenv("MIN_DEPOSIT_USD", "5"))

# Filet de secours : revérifie périodiquement le statut des dépôts non
# encore crédités auprès de l'API NOWPayments, au cas où la notification
# IPN n'arriverait jamais (Railway injoignable, notification perdue...).
# Un dépôt encore en attente après DEPOSIT_POLL_MAX_AGE_HOURS n'est plus
# revérifié (évite une croissance illimitée du travail de fond) et passe
# en statut "expired".
DEPOSIT_POLL_INTERVAL_SECONDS: int = int(os.getenv("DEPOSIT_POLL_INTERVAL_SECONDS", "60"))
DEPOSIT_POLL_MAX_AGE_HOURS: int = int(os.getenv("DEPOSIT_POLL_MAX_AGE_HOURS", "24"))

# Nettoyage des réservations de stock et commandes orphelines : si le bot
# crashe entre la réservation d'une unité de stock et la fin de l'achat
# (débit + livraison), l'unité resterait bloquée en "reserved" et la
# commande en "pending" pour toujours sans ce filet de secours. En
# fonctionnement normal, un achat se résout en quelques secondes ; un délai
# largement supérieur ne peut donc s'expliquer que par une interruption.
STALE_RESERVATION_TIMEOUT_MINUTES: int = int(os.getenv("STALE_RESERVATION_TIMEOUT_MINUTES", "15"))

# --- Serveur interne (health check + webhook NOWPayments) ---
PORT: int = int(os.getenv("PORT", "8080"))
WEBHOOK_PATH: str = "/ipn/nowpayments"

# --- Divers ---
SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "@support")
LOW_STOCK_THRESHOLD: int = int(os.getenv("LOW_STOCK_THRESHOLD", "3"))
CURRENCY_SYMBOL: str = "$"
