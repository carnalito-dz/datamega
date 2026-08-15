"""
Tâches de fond de maintenance.

1. Filet de secours pour les dépôts crypto.

   Le webhook IPN (webhook/server.py) est le mécanisme normal de
   confirmation d'un dépôt. Mais si Railway est temporairement injoignable
   au moment où NOWPayments tente de notifier, ou si la notification est
   perdue pour toute autre raison, un dépôt resterait bloqué en `waiting`
   indéfiniment sans que le client ne soit jamais crédité — sans même une
   alerte, puisque rien ne le reverifie.

   Cette tâche revérifie périodiquement, auprès de l'API NOWPayments
   elle-même, le statut de chaque dépôt non encore crédité. Elle réutilise
   exactement la même logique de crédit que le webhook
   (services/deposits.py), donc aucune divergence de comportement entre
   les deux chemins. Passé DEPOSIT_POLL_MAX_AGE_HOURS sans confirmation,
   un dépôt n'est plus revérifié et passe en statut `expired`.

2. Nettoyage des réservations de stock et commandes orphelines.

   Si le bot crashe (ou est redémarré) entre la réservation atomique
   d'une unité de stock et la fin de l'achat (débit + livraison), cette
   unité resterait bloquée en `reserved` pour toujours — invendable, sans
   jamais être ni vendue ni relâchée — et la commande correspondante en
   `pending` pour toujours. Cette tâche libère ce qui est resté bloqué
   plus longtemps que STALE_RESERVATION_TIMEOUT_MINUTES (un achat normal
   se résout en quelques secondes).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot
from sqlalchemy import select, update

import config
from db.models import Deposit, DepositStatus, Order, OrderStatus
from db.session import get_session
from services import deposits, nowpayments, stock

logger = logging.getLogger("datamega.background")


async def _poll_deposits_once(bot: Bot) -> None:
    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=config.DEPOSIT_POLL_MAX_AGE_HOURS)

    async with get_session() as session:
        result = await session.execute(
            select(Deposit).where(
                Deposit.credited.is_(False),
                Deposit.status.in_([DepositStatus.WAITING, DepositStatus.CONFIRMING]),
            )
        )
        pending = list(result.scalars().all())

    for deposit in pending:
        if deposit.created_at < cutoff:
            async with get_session() as session:
                fresh = await session.get(Deposit, deposit.id)
                if fresh and not fresh.credited:
                    fresh.status = DepositStatus.EXPIRED
                    await session.commit()
                    logger.info("Dépôt #%s expiré après %sh sans confirmation",
                                deposit.id, config.DEPOSIT_POLL_MAX_AGE_HOURS)
            continue

        try:
            payload = await nowpayments.get_payment_status(deposit.payment_id)
        except nowpayments.NowPaymentsError as exc:
            logger.warning("Poll dépôt #%s (%s) échoué : %s", deposit.id, deposit.payment_id, exc)
            continue

        payment_status = payload.get("payment_status", "")

        async with get_session() as session:
            fresh = await session.get(Deposit, deposit.id)
            if not fresh or fresh.credited:
                continue
            credited_now = await deposits.apply_status_update(session, fresh, payment_status, bot)
            if credited_now:
                logger.info("Dépôt #%s crédité via le filet de secours (payment_status=%s)",
                            deposit.id, payment_status)


async def _cleanup_stale_reservations_once() -> None:
    cutoff = dt.datetime.utcnow() - dt.timedelta(minutes=config.STALE_RESERVATION_TIMEOUT_MINUTES)

    async with get_session() as session:
        n_units = await stock.release_stale_reservations(session, cutoff)
        if n_units:
            logger.info("%s unité(s) de stock orpheline(s) libérée(s) (bloquées depuis > %s min)",
                        n_units, config.STALE_RESERVATION_TIMEOUT_MINUTES)

        # Commandes restées en `pending` au-delà du même délai : l'achat a
        # été interrompu avant d'aboutir (débit + livraison). On les
        # marque `failed` pour l'historique — aucun impact financier ici,
        # le débit n'a par définition pas eu lieu pour une commande encore
        # `pending`.
        result = await session.execute(
            update(Order)
            .where(Order.status == OrderStatus.PENDING, Order.created_at < cutoff)
            .values(status=OrderStatus.FAILED, error_note="Achat interrompu (nettoyage automatique)")
        )
        await session.commit()
        if result.rowcount:
            logger.info("%s commande(s) orpheline(s) marquée(s) 'failed'", result.rowcount)


async def run_maintenance_loop(bot: Bot) -> None:
    """Boucle infinie à lancer en tâche de fond (voir main.py)."""
    logger.info(
        "Tâches de fond démarrées (dépôts : intervalle %ss / expiration %sh ; "
        "réservations orphelines : seuil %s min)",
        config.DEPOSIT_POLL_INTERVAL_SECONDS, config.DEPOSIT_POLL_MAX_AGE_HOURS,
        config.STALE_RESERVATION_TIMEOUT_MINUTES,
    )
    while True:
        try:
            await _poll_deposits_once(bot)
        except Exception:  # noqa: BLE001
            # Une erreur inattendue sur un cycle ne doit jamais arrêter
            # définitivement la boucle : on logue et on continue au
            # prochain intervalle.
            logger.exception("Erreur pendant le cycle de revérification des dépôts")

        try:
            await _cleanup_stale_reservations_once()
        except Exception:  # noqa: BLE001
            logger.exception("Erreur pendant le nettoyage des réservations orphelines")

        await asyncio.sleep(config.DEPOSIT_POLL_INTERVAL_SECONDS)
