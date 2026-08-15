"""
Client NOWPayments minimal (backend uniquement, aucune redirection web).

Le client choisit un montant + une crypto dans Telegram ; on crée un
paiement via l'API NOWPayments et on affiche adresse/montant/QR code
directement dans le chat. La confirmation arrive via webhook IPN.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import uuid

import aiohttp
import qrcode

import config


class NowPaymentsError(Exception):
    pass


def _headers() -> dict:
    return {
        "x-api-key": config.NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json",
    }


async def create_payment(amount_usd: float, currency: str, order_id: str) -> dict:
    """
    Crée un paiement NOWPayments et retourne le payload brut
    (contient payment_id, pay_address, pay_amount, etc.)
    """
    url = f"{config.NOWPAYMENTS_API_URL}/payment"
    payload = {
        "price_amount": amount_usd,
        "price_currency": "usd",
        "pay_currency": currency,
        "order_id": order_id,
        "order_description": f"Recharge solde DATA MEGA - {order_id}",
    }
    async with aiohttp.ClientSession() as http:
        async with http.post(url, headers=_headers(), json=payload) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise NowPaymentsError(data.get("message", "Erreur NOWPayments"))
            return data


async def get_payment_status(payment_id: str) -> dict:
    url = f"{config.NOWPAYMENTS_API_URL}/payment/{payment_id}"
    async with aiohttp.ClientSession() as http:
        async with http.get(url, headers=_headers()) as resp:
            data = await resp.json()
            if resp.status >= 400:
                raise NowPaymentsError(data.get("message", "Erreur NOWPayments"))
            return data


def new_order_id() -> str:
    return uuid.uuid4().hex[:16]


def make_qr_png(data: str) -> io.BytesIO:
    """Génère un QR code PNG en mémoire pour l'adresse de paiement."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "qr.png"
    return buf


def verify_ipn_signature(raw_body: bytes, received_signature: str) -> bool:
    """
    Vérifie la signature HMAC-SHA512 envoyée par NOWPayments dans le
    header x-nowpayments-sig, calculée sur le JSON trié par clés.
    """
    if not config.NOWPAYMENTS_IPN_SECRET:
        # Pas de secret configuré : on refuse par sécurité en prod,
        # mais on log clairement pour le débogage.
        return False
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        return False
    sorted_body = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    computed = hmac.new(
        config.NOWPAYMENTS_IPN_SECRET.encode(),
        sorted_body.encode(),
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(computed, received_signature or "")
