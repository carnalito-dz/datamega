"""Point d'entrée DATA MEGA V3 — bot complet."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

import config
from db.session import init_db
from middlewares import BanMiddleware, LabelsMiddleware, MaintenanceMiddleware
from services.background_tasks import run_maintenance_loop
from webhook.server import create_app

# ── Handlers admin ─────────────────────────────────────────────────────────
from handlers.admin import (
    broadcast,
    keyword_import as admin_keyword_import,
    categories as admin_categories,
    clients as admin_clients,
    dashboard as admin_dashboard,
    keywords as admin_keywords,
    labels as admin_labels,
    logs as admin_logs,
    messaging as admin_messaging,
    notifications as admin_notifications,
    orders as admin_orders,
    products as admin_products,
    promo as admin_promo,
    settings as admin_settings,
    stats as admin_stats,
    stock as admin_stock,
    wallet_admin,
)

# ── Handlers user ───────────────────────────────────────────────────────────
from handlers.user import (
    account,
    shop,
    start,
    support,
    wallet as user_wallet,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("datamega")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares — ordre : Ban → Maintenance → Labels
    dp.message.outer_middleware(BanMiddleware())
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.message.outer_middleware(LabelsMiddleware())
    dp.callback_query.outer_middleware(LabelsMiddleware())

    # Routers admin (filtre IsAdmin intégré dans chaque router)
    dp.include_router(admin_dashboard.router)
    dp.include_router(admin_categories.router)
    dp.include_router(admin_products.router)
    dp.include_router(admin_stock.router)
    dp.include_router(admin_clients.router)
    dp.include_router(wallet_admin.router)
    dp.include_router(admin_orders.router)
    dp.include_router(admin_stats.router)
    dp.include_router(admin_notifications.router)
    dp.include_router(admin_logs.router)
    dp.include_router(admin_settings.router)
    dp.include_router(admin_labels.router)
    dp.include_router(admin_messaging.router)
    dp.include_router(admin_promo.router)
    dp.include_router(broadcast.router)
    dp.include_router(admin_keywords.router)
    dp.include_router(admin_keyword_import.router)

    # Routers client
    dp.include_router(start.router)
    dp.include_router(shop.router)
    dp.include_router(user_wallet.router)
    dp.include_router(account.router)
    dp.include_router(support.router)

    return dp


async def main() -> None:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN manquant dans les variables d'environnement.")
    if not config.ADMIN_IDS:
        logger.warning("ADMIN_IDS vide — le panel /admin sera inaccessible.")

    await init_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    # Serveur webhook IPN
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
    await site.start()
    logger.info("Serveur web démarré sur le port %s", config.PORT)

    # Tâches de fond
    bg_task = asyncio.create_task(run_maintenance_loop(bot))

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Démarrage du polling Telegram…")
        await dp.start_polling(bot)
    finally:
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
