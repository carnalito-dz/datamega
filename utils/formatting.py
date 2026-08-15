"""Fonctions de formatage pour l'affichage."""
from __future__ import annotations

import datetime as dt


def fmt_money(amount_cents: int, symbol: str = "$") -> str:
    """Formate un montant en centimes en chaîne lisible."""
    return f"{amount_cents / 100:.2f}{symbol}"


def fmt_datetime(d: dt.datetime | None) -> str:
    """Formate une date/heure UTC en chaîne lisible."""
    if d is None:
        return "—"
    return d.strftime("%d/%m/%Y %H:%M")


def fmt_date(d: dt.datetime | None) -> str:
    if d is None:
        return "—"
    return d.strftime("%d/%m/%Y")


def truncate(text: str, max_len: int = 50) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"
