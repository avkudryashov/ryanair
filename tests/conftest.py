import pytest
import json
import time
import tempfile
import os
import diskcache

from flight_search import FlightSearcher


# ── Фикстуры с мок-данными ──────────────────────────────

AIRPORTS_RESPONSE = [
    {
        "code": "VLC", "name": "Valencia",
        "city": {"name": "Valencia"},
        "country": {"name": "Spain", "code": "es", "schengen": True}
    },
    {
        "code": "BGY", "name": "Milan Bergamo",
        "city": {"name": "Bergamo"},
        "country": {"name": "Italy", "code": "it", "schengen": True}
    },
    {
        "code": "MXP", "name": "Milan Malpensa",
        "city": {"name": "Milan"},
        "country": {"name": "Italy", "code": "it", "schengen": True}
    },
    {
        "code": "STN", "name": "London Stansted",
        "city": {"name": "London"},
        "country": {"name": "United Kingdom", "code": "gb", "schengen": False}
    },
    {
        "code": "AGP", "name": "Malaga",
        "city": {"name": "Malaga"},
        "country": {"name": "Spain", "code": "es", "schengen": True}
    },
]

FARFND_RESPONSE = {
    "fares": [
        {
            "outbound": {
                "arrivalAirport": {"iataCode": "BGY", "name": "Milan Bergamo", "countryName": "Italy"},
                "price": {"value": 15.0, "currencyCode": "EUR"}
            }
        },
        {
            "outbound": {
                "arrivalAirport": {"iataCode": "MXP", "name": "Milan Malpensa", "countryName": "Italy"},
                "price": {"value": 20.0, "currencyCode": "EUR"}
            }
        },
        {
            "outbound": {
                "arrivalAirport": {"iataCode": "STN", "name": "London Stansted", "countryName": "United Kingdom"},
                "price": {"value": 10.0, "currencyCode": "EUR"}
            }
        },
        {
            "outbound": {
                "arrivalAirport": {"iataCode": "AGP", "name": "Malaga", "countryName": "Spain"},
                "price": {"value": 12.0, "currencyCode": "EUR"}
            }
        },
    ]
}


def make_availability_response(origin, destination, flights_data):
    """Создаёт ответ Availability API из списка рейсов."""
    flights = []
    for dep, arr, price, flight_num in flights_data:
        flights.append({
            "segments": [{
                "origin": origin,
                "destination": destination,
                "flightNumber": flight_num,
                "time": [dep, arr]
            }],
            "regularFare": {
                "fares": [{"amount": price}]
            }
        })
    return {
        "trips": [{
            "originName": origin,
            "destinationName": destination,
            "dates": [{"flights": flights}]
        }]
    }


@pytest.fixture
def tmp_cache_dir(tmp_path):
    """Временная директория для кэша."""
    return str(tmp_path / "cache")


@pytest.fixture
def searcher(tmp_cache_dir):
    """FlightSearcher с чистым временным кэшем."""
    s = FlightSearcher()
    s._cache.close()
    s._cache = diskcache.Cache(tmp_cache_dir)
    return s
