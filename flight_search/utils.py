"""Shared utilities: deduplication, filtering."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Destination, Flight


def deduplicate_flights(flights: list[Flight], key_fields=('flight_number', 'departure_time')) -> list[Flight]:
    """Remove duplicate flights by (flight_number, departure_time)."""
    seen: set = set()
    unique: list = []
    for f in flights:
        key = tuple(getattr(f, k) for k in key_fields)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def filter_excluded(
    destinations: dict[str, Destination],
    excluded_airports: set[str] | None = None,
    excluded_countries: set[str] | None = None,
) -> dict[str, Destination]:
    """Filter destinations by excluded airports and countries."""
    result = destinations
    if excluded_airports:
        result = {c: i for c, i in result.items() if c not in excluded_airports}
    if excluded_countries:
        result = {c: i for c, i in result.items() if i.country not in excluded_countries}
    return result


def build_exclusion_sets(config: dict, excluded_airports=None, excluded_countries=None):
    """Merge config exclusions with overrides into sets."""
    ap = set(config.get('excluded_airports', []))
    if excluded_airports:
        ap.update(excluded_airports)
    co = set(config.get('excluded_countries', []))
    if excluded_countries:
        co.update(excluded_countries)
    return ap, co
