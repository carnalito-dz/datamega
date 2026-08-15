"""Utilitaires de conversion monétaire."""
from __future__ import annotations


class InvalidAmount(ValueError):
    pass


def parse_usd_to_cents(raw: str) -> int:
    """Convertit une chaîne USD en centimes entiers. Lève InvalidAmount si invalide."""
    try:
        value = float(raw.strip().replace(",", "."))
    except ValueError:
        raise InvalidAmount(f"Montant invalide : « {raw} »")
    if value <= 0:
        raise InvalidAmount("Le montant doit être strictement positif.")
    if value > 100_000:
        raise InvalidAmount("Le montant est trop élevé.")
    return round(value * 100)


def dollars_to_cents(raw: str) -> int:
    """Alias de parse_usd_to_cents."""
    return parse_usd_to_cents(raw)


def cents_to_dollars(cents: int) -> float:
    return cents / 100
