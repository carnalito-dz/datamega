"""
Serveur aiohttp interne :
  - GET  /health              -> vérification Railway
  - POST /ipn/nowpayments     -> webhook NOWPayments (idempotent)

Ce serveur tourne en parallèle du polling aiogram (voir main.py).

La logique de crédit d'un dépôt est centralisée dans services/deposits.py,
partagée avec la tâche de fond de secours (services/background_tasks.py).
"""
from __future__ import annotations

import json

from aiogram import Bot
from aiohttp import web
from sqlalchemy import select

import config
from db.models import Deposit
from db.session import get_session
from services import deposits, nowpayments


def create_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/health", health)
    app.router.add_post(config.WEBHOOK_PATH, nowpayments_ipn)
    return app


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def nowpayments_ipn(request: web.Request) -> web.Response:
    raw_body = await request.read()
    signature = request.headers.get("x-nowpayments-sig", "")

    if not nowpayments.verify_ipn_signature(raw_body, signature):
        return web.json_response({"error": "invalid signature"}, status=401)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid json"}, status=400)

    payment_id = str(payload.get("payment_id", ""))
    payment_status = payload.get("payment_status", "")
    if not payment_id:
        return web.json_response({"error": "missing payment_id"}, status=400)

    bot: Bot = request.app["bot"]

    async with get_session() as session:
        result = await session.execute(select(Deposit).where(Deposit.payment_id == payment_id))
        deposit = result.scalar_one_or_none()
        if not deposit:
            # Paiement inconnu de notre base : on répond 200 pour éviter les
            # retries infinis, mais on n'accorde aucun crédit.
            return web.json_response({"status": "ignored_unknown_payment"})

        await deposits.apply_status_update(session, deposit, payment_status, bot)

    return web.json_response({"status": "ok"})
