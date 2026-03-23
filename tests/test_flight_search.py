"""Unit-тесты для FlightSearcher: парсинг, комбинирование, батчинг."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from flight_search import FlightSearcher, TTL_AIRPORTS, TTL_DESTINATIONS, TTL_FLIGHTS
from tests.conftest import (
    AIRPORTS_RESPONSE, FARFND_RESPONSE,
    make_availability_response
)


class TestParseFlights:
    """Тесты парсинга ответа Availability API."""

    def test_parse_flights_basic(self, searcher):
        data = make_availability_response("VLC", "BGY", [
            ("2026-05-20T10:00:00", "2026-05-20T12:00:00", 25.0, "FR 123"),
            ("2026-05-21T08:00:00", "2026-05-21T10:00:00", 30.0, "FR 456"),
        ])
        flights = searcher._parse_flights(data, "Milan Bergamo")
        assert len(flights) == 2
        assert flights[0]['origin'] == "VLC"
        assert flights[0]['destination'] == "BGY"
        assert flights[0]['price'] == 25.0
        assert flights[0]['flightNumber'] == "FR 123"
        assert isinstance(flights[0]['departureTime'], datetime)

    def test_parse_flights_skips_no_segments(self, searcher):
        data = {"trips": [{"dates": [{"flights": [{"segments": [], "regularFare": {"fares": [{"amount": 10}]}}]}]}]}
        flights = searcher._parse_flights(data)
        assert len(flights) == 0

    def test_parse_flights_skips_no_fare(self, searcher):
        data = {"trips": [{"dates": [{"flights": [{
            "segments": [{"origin": "VLC", "destination": "BGY", "flightNumber": "FR1",
                          "time": ["2026-05-20T10:00:00", "2026-05-20T12:00:00"]}],
            "regularFare": {"fares": []}
        }]}]}]}
        flights = searcher._parse_flights(data)
        assert len(flights) == 0

    def test_parse_flights_empty_response(self, searcher):
        flights = searcher._parse_flights({})
        assert flights == []


class TestFlightCacheable:
    """Тесты конвертации в/из формата кэша."""

    def test_roundtrip(self, searcher):
        flight = {
            'origin': 'VLC', 'destination': 'BGY',
            'departureTime': datetime(2026, 5, 20, 10, 0),
            'arrivalTime': datetime(2026, 5, 20, 12, 0),
            'flightNumber': 'FR 123', 'price': 25.0, 'currency': 'EUR'
        }
        cached = searcher._flight_to_cacheable(flight)
        assert isinstance(cached['departureTime'], str)

        restored = searcher._restore_datetimes([cached])
        assert len(restored) == 1
        assert isinstance(restored[0]['departureTime'], datetime)
        assert restored[0]['departureTime'] == flight['departureTime']


class TestCombineFlights:
    """Тесты комбинирования рейсов туда/обратно."""

    def _make_flight(self, dep_str, arr_str, price=20.0, dest="BGY", flight_num="FR1"):
        return {
            'origin': 'VLC', 'destination': dest,
            'originName': 'Valencia', 'destinationName': 'Milan Bergamo',
            'departureTime': datetime.fromisoformat(dep_str),
            'arrivalTime': datetime.fromisoformat(arr_str),
            'flightNumber': flight_num, 'price': price, 'currency': 'EUR'
        }

    def test_combine_1_night(self, searcher):
        outbound = {"BGY": [self._make_flight("2026-05-20T10:00:00", "2026-05-20T12:00:00", 20.0)]}
        inbound = {"BGY": [self._make_flight("2026-05-21T18:00:00", "2026-05-21T20:00:00", 25.0)]}

        results = searcher._combine_flights(outbound, inbound, night_count=1, max_price=100)
        assert len(results) == 1
        assert results[0]['totalPrice'] == 45.0
        assert results[0]['nights'] == 1

    def test_combine_rejects_wrong_nights(self, searcher):
        outbound = {"BGY": [self._make_flight("2026-05-20T10:00:00", "2026-05-20T12:00:00", 20.0)]}
        # 3 ночи — не подходит для night_count=1
        inbound = {"BGY": [self._make_flight("2026-05-23T18:00:00", "2026-05-23T20:00:00", 25.0)]}

        results = searcher._combine_flights(outbound, inbound, night_count=1, max_price=100)
        assert len(results) == 0

    def test_combine_rejects_over_max_price(self, searcher):
        outbound = {"BGY": [self._make_flight("2026-05-20T10:00:00", "2026-05-20T12:00:00", 60.0)]}
        inbound = {"BGY": [self._make_flight("2026-05-21T18:00:00", "2026-05-21T20:00:00", 60.0)]}

        results = searcher._combine_flights(outbound, inbound, night_count=1, max_price=100)
        assert len(results) == 0

    def test_combine_rejects_late_arrival(self, searcher):
        # Прилёт в 23:30 — после max_arrival_time (22:00 в config)
        outbound = {"BGY": [self._make_flight("2026-05-20T21:00:00", "2026-05-20T23:30:00", 20.0)]}
        inbound = {"BGY": [self._make_flight("2026-05-21T18:00:00", "2026-05-21T20:00:00", 25.0)]}

        results = searcher._combine_flights(outbound, inbound, night_count=1, max_price=100)
        assert len(results) == 0

    def test_combine_calendar_nights_correct(self, searcher):
        """Рейс 20.05 вечером → 22.05 утром = 2 календарные ночи."""
        outbound = {"BGY": [self._make_flight("2026-05-20T19:00:00", "2026-05-20T21:00:00", 20.0)]}
        inbound = {"BGY": [self._make_flight("2026-05-22T07:00:00", "2026-05-22T09:00:00", 25.0)]}

        results_1 = searcher._combine_flights(outbound, inbound, night_count=1, max_price=100)
        results_2 = searcher._combine_flights(outbound, inbound, night_count=2, max_price=100)

        assert len(results_1) == 0  # не 1 ночь
        assert len(results_2) == 1  # именно 2 ночи

    def test_combine_no_inbound_flights(self, searcher):
        outbound = {"BGY": [self._make_flight("2026-05-20T10:00:00", "2026-05-20T12:00:00")]}
        results = searcher._combine_flights(outbound, {}, night_count=1, max_price=100)
        assert len(results) == 0


class TestDateBatches:
    """Тесты разбиения дат на батчи (лимит FlexDaysOut=6)."""

    def test_small_range_single_batch(self, searcher):
        batches = searcher._build_date_batches("2026-05-17", "2026-05-22")
        assert len(batches) == 1
        assert batches[0] == ("2026-05-17", 5)

    def test_exact_max_single_batch(self, searcher):
        batches = searcher._build_date_batches("2026-05-17", "2026-05-23")
        assert len(batches) == 1
        assert batches[0] == ("2026-05-17", 6)

    def test_over_max_two_batches(self, searcher):
        batches = searcher._build_date_batches("2026-05-17", "2026-05-25")
        assert len(batches) == 2
        # Первый батч: 17 мая + 6 = до 23 мая
        assert batches[0] == ("2026-05-17", 6)
        # Второй батч: 24 мая + остаток
        assert batches[1][0] == "2026-05-24"

    def test_large_range_multiple_batches(self, searcher):
        batches = searcher._build_date_batches("2026-05-01", "2026-05-20")
        assert len(batches) >= 3
        # Все flex <= 6
        for _, flex in batches:
            assert flex <= 6

    def test_zero_range(self, searcher):
        batches = searcher._build_date_batches("2026-05-17", "2026-05-17")
        assert len(batches) == 1
        assert batches[0] == ("2026-05-17", 0)


class TestGetAirports:
    """Тесты получения аэропортов."""

    def test_get_airports_parses_response(self, searcher):
        with patch('httpx.get') as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: AIRPORTS_RESPONSE,
                raise_for_status=lambda: None
            )
            airports = searcher.get_airports()

        assert len(airports) == 5
        codes = {ap['code'] for ap in airports}
        assert 'VLC' in codes
        assert 'BGY' in codes
        # Отсортированы по name
        names = [ap['name'] for ap in airports]
        assert names == sorted(names)

    def test_get_airports_cached(self, searcher):
        with patch('httpx.get') as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: AIRPORTS_RESPONSE,
                raise_for_status=lambda: None
            )
            airports1 = searcher.get_airports()
            airports2 = searcher.get_airports()

        # API вызван только 1 раз
        assert mock_get.call_count == 1
        assert len(airports1) == len(airports2)

    def test_get_airports_returns_stale_on_error(self, searcher):
        # Заполняем кэш
        import time as _time
        key = "airports:all_active"
        searcher._cache.set(key, ([{"code": "VLC", "name": "Valencia"}], _time.time() - 100000), expire=700000)

        with patch('httpx.get', side_effect=Exception("Network error")):
            airports = searcher.get_airports()

        assert len(airports) == 1
        assert airports[0]['code'] == 'VLC'


class TestDataFreshness:
    def test_freshness_initial(self, searcher):
        f = searcher.get_data_freshness()
        assert f['age_minutes'] is None

    def test_freshness_after_api_call(self, searcher):
        import time as _time
        searcher._last_api_call_ts = _time.time()
        f = searcher.get_data_freshness()
        assert f['age_minutes'] == 0
        assert f['stale'] is False

    def test_freshness_stale_flag(self, searcher):
        import time as _time
        searcher._last_api_call_ts = _time.time() - 600  # 10 мин назад
        searcher._served_from_stale = True
        f = searcher.get_data_freshness()
        assert f['stale'] is True
        assert f['age_minutes'] == 10
