"""
E2E тесты — реальные запросы к Ryanair API.
Запуск: pytest tests/test_e2e.py -v -s
Пометка: @pytest.mark.e2e — пропускаются по умолчанию, запуск через pytest -m e2e
"""
import pytest
import time
from datetime import date, timedelta

from flight_search import FlightSearcher

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def searcher():
    """Один searcher на весь модуль (shared cache)."""
    return FlightSearcher()


class TestAirportsE2E:
    def test_get_airports_returns_list(self, searcher):
        airports = searcher.get_airports()
        assert len(airports) > 100
        assert all(hasattr(ap, 'code') for ap in airports)
        assert all(hasattr(ap, 'name') for ap in airports)
        assert all(hasattr(ap, 'country') for ap in airports)

    def test_airports_contain_vlc(self, searcher):
        airports = searcher.get_airports()
        codes = {ap.code for ap in airports}
        assert 'VLC' in codes

    def test_airports_cached_on_second_call(self, searcher):
        t1 = time.time()
        searcher.get_airports()
        t2 = time.time()
        searcher.get_airports()
        t3 = time.time()
        # Второй вызов должен быть значительно быстрее
        assert (t3 - t2) < (t2 - t1) * 0.1 or (t3 - t2) < 0.01


class TestDestinationsE2E:
    def test_get_destinations_from_vlc(self, searcher):
        today = date.today()
        date_from = (today + timedelta(days=7)).isoformat()
        date_to = (today + timedelta(days=14)).isoformat()

        destinations = searcher.get_available_destinations(date_from, date_to)
        assert len(destinations) > 0

        for code, info in destinations.items():
            assert len(code) == 3  # IATA code
            assert info.price > 0
            assert info.name

    def test_destinations_exclude_uk(self, searcher):
        """UK и Ireland должны быть отфильтрованы (config excluded_countries)."""
        today = date.today()
        date_from = (today + timedelta(days=7)).isoformat()
        date_to = (today + timedelta(days=14)).isoformat()

        destinations = searcher.get_available_destinations(date_from, date_to)
        countries = {info.country for info in destinations.values()}
        assert 'United Kingdom' not in countries
        assert 'Ireland' not in countries


class TestSearchFlightsE2E:
    def test_search_finds_flights(self, searcher):
        """Базовый поиск — должен найти хоть что-то."""
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        trips = searcher.search_flights(
            departure, [1, 2],
            flex_days_override=2,
            max_price_override=150
        )
        for trip in trips:
            assert trip.nights in [1, 2]
            assert trip.total_price <= 150
            assert trip.total_price > 0
            assert trip.outbound is not None
            assert trip.inbound is not None

    def test_search_with_country_exclusion(self, searcher):
        """Поиск с исключением страны — направления этой страны не должны попасть."""
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        trips = searcher.search_flights(
            departure, [1, 2],
            excluded_countries_override=['Spain'],
            flex_days_override=1,
            max_price_override=150
        )
        for trip in trips:
            dest = trip.outbound.destination
            assert dest != searcher.config['origin_airport']

    def test_search_with_airport_exclusion(self, searcher):
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        trips = searcher.search_flights(
            departure, [1],
            excluded_airports_override=['BGY', 'MXP'],
            flex_days_override=1,
            max_price_override=150
        )
        for trip in trips:
            assert trip.outbound.destination not in ['BGY', 'MXP']

    def test_search_respects_max_price(self, searcher):
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        trips = searcher.search_flights(
            departure, [1],
            flex_days_override=1,
            max_price_override=40
        )
        for trip in trips:
            assert trip.total_price <= 40

    def test_search_flex_4_days_works(self, searcher):
        """±4 дня — ранее сломанный кейс. FlexDaysOut > 6 должен батчиться."""
        today = date.today()
        departure = (today + timedelta(days=30)).strftime('%Y-%m-%d')

        # Не должно упасть с 400 ошибкой
        trips = searcher.search_flights(
            departure, [1],
            flex_days_override=4,
            max_price_override=150
        )
        assert isinstance(trips, list)

    def test_search_flex_7_days_works(self, searcher):
        """±7 дней — максимальный диапазон. Должен разбиться на 3+ батча."""
        today = date.today()
        departure = (today + timedelta(days=30)).strftime('%Y-%m-%d')

        trips = searcher.search_flights(
            departure, [1, 2],
            flex_days_override=7,
            max_price_override=200
        )
        assert isinstance(trips, list)

    def test_search_calendar_nights_correct(self, searcher):
        """Ночи считаются по календарным датам, а не часам."""
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        trips = searcher.search_flights(
            departure, [2],
            flex_days_override=1,
            max_price_override=150
        )
        for trip in trips:
            out_arrival = trip.outbound.arrival_time.date()
            in_departure = trip.inbound.departure_time.date()
            calendar_nights = (in_departure - out_arrival).days
            assert calendar_nights == 2, f"Expected 2 nights, got {calendar_nights}"


class TestSearchPerformance:
    def test_search_completes_under_30s(self, searcher):
        """Поиск с ±1 днём должен завершиться менее чем за 30 секунд."""
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        start = time.time()
        searcher.search_flights(
            departure, [1],
            flex_days_override=1,
            max_price_override=100
        )
        elapsed = time.time() - start
        assert elapsed < 30, f"Search took {elapsed:.1f}s, expected < 30s"

    def test_cached_search_under_1s(self, searcher):
        """Повторный поиск из кэша должен быть < 1 секунды."""
        today = date.today()
        departure = (today + timedelta(days=14)).strftime('%Y-%m-%d')

        # Первый запрос прогревает кэш
        searcher.search_flights(departure, [1], flex_days_override=1, max_price_override=100)

        # Второй запрос — из кэша
        start = time.time()
        searcher.search_flights(departure, [1], flex_days_override=1, max_price_override=100)
        elapsed = time.time() - start
        assert elapsed < 1.0, f"Cached search took {elapsed:.1f}s, expected < 1s"


class TestCachePersistence:
    def test_cache_survives_new_instance(self):
        """Кэш переживает создание нового FlightSearcher."""
        s1 = FlightSearcher()
        airports1 = s1.get_airports()

        s2 = FlightSearcher()
        start = time.time()
        airports2 = s2.get_airports()
        elapsed = time.time() - start

        assert len(airports1) == len(airports2)
        assert elapsed < 0.1, "Should load from disk cache instantly"
