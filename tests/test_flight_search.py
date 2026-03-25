"""Unit-тесты для FlightSearcher: парсинг, комбинирование, батчинг."""
import time as _time

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from flight_search import FlightSearcher
from flight_search.client import _is_retryable
from flight_search.cache import TTL_AIRPORTS, TTL_DESTINATIONS, TTL_FLIGHTS
from models import Flight, Trip, Airport, Destination
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
        flights = searcher._client._parse_flights(data, "Milan Bergamo")
        assert len(flights) == 2
        assert flights[0].origin == "VLC"
        assert flights[0].destination == "BGY"
        assert flights[0].price == 25.0
        assert flights[0].flight_number == "FR 123"
        assert isinstance(flights[0].departure_time, datetime)
        assert isinstance(flights[0], Flight)

    def test_parse_flights_skips_no_segments(self, searcher):
        data = {"trips": [{"dates": [{"flights": [{"segments": [], "regularFare": {"fares": [{"amount": 10}]}}]}]}]}
        flights = searcher._client._parse_flights(data)
        assert len(flights) == 0

    def test_parse_flights_skips_no_fare(self, searcher):
        data = {"trips": [{"dates": [{"flights": [{
            "segments": [{"origin": "VLC", "destination": "BGY", "flightNumber": "FR1",
                          "time": ["2026-05-20T10:00:00", "2026-05-20T12:00:00"]}],
            "regularFare": {"fares": []}
        }]}]}]}
        flights = searcher._client._parse_flights(data)
        assert len(flights) == 0

    def test_parse_flights_empty_response(self, searcher):
        flights = searcher._client._parse_flights({})
        assert flights == []


class TestFlightCacheable:
    """Тесты конвертации в/из формата кэша."""

    def test_roundtrip(self, searcher):
        flight = Flight(
            origin='VLC', destination='BGY',
            departure_time=datetime(2026, 5, 20, 10, 0),
            arrival_time=datetime(2026, 5, 20, 12, 0),
            flight_number='FR 123', price=25.0, currency='EUR'
        )
        cached = flight.model_dump(mode='json')
        assert isinstance(cached['departure_time'], str)

        restored = Flight.model_validate(cached)
        assert isinstance(restored.departure_time, datetime)
        assert restored.departure_time == flight.departure_time


class TestCombineFlights:
    """Тесты комбинирования рейсов туда/обратно."""

    def _make_flight(self, dep_str, arr_str, price=20.0, dest="BGY", flight_num="FR1"):
        return Flight(
            origin='VLC', destination=dest,
            origin_name='Valencia', destination_name='Milan Bergamo',
            departure_time=datetime.fromisoformat(dep_str),
            arrival_time=datetime.fromisoformat(arr_str),
            flight_number=flight_num, price=price, currency='EUR'
        )

    def test_combine_1_night(self, searcher):
        outbound = {"BGY": [self._make_flight("2026-05-20T10:00:00", "2026-05-20T12:00:00", 20.0)]}
        inbound = {"BGY": [self._make_flight("2026-05-21T18:00:00", "2026-05-21T20:00:00", 25.0)]}

        results = searcher._combine_flights(outbound, inbound, night_count=1, max_price=100)
        assert len(results) == 1
        assert results[0].total_price == 45.0
        assert results[0].nights == 1
        assert isinstance(results[0], Trip)

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
        batches = searcher._client.build_date_batches("2026-05-17", "2026-05-22")
        assert len(batches) == 1
        assert batches[0] == ("2026-05-17", 5)

    def test_exact_max_single_batch(self, searcher):
        batches = searcher._client.build_date_batches("2026-05-17", "2026-05-23")
        assert len(batches) == 1
        assert batches[0] == ("2026-05-17", 6)

    def test_over_max_two_batches(self, searcher):
        batches = searcher._client.build_date_batches("2026-05-17", "2026-05-25")
        assert len(batches) == 2
        assert batches[0] == ("2026-05-17", 6)
        assert batches[1][0] == "2026-05-24"

    def test_large_range_multiple_batches(self, searcher):
        batches = searcher._client.build_date_batches("2026-05-01", "2026-05-20")
        assert len(batches) >= 3
        for _, flex in batches:
            assert flex <= 6

    def test_zero_range(self, searcher):
        batches = searcher._client.build_date_batches("2026-05-17", "2026-05-17")
        assert len(batches) == 1
        assert batches[0] == ("2026-05-17", 0)


class TestGetAirports:
    """Тесты получения аэропортов."""

    def test_get_airports_parses_response(self, searcher):
        with patch('flight_search.client.httpx.get') as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: AIRPORTS_RESPONSE,
                raise_for_status=lambda: None
            )
            airports = searcher.get_airports()

        assert len(airports) == 5
        codes = {ap.code for ap in airports}
        assert 'VLC' in codes
        assert 'BGY' in codes
        # Отсортированы по name
        names = [ap.name for ap in airports]
        assert names == sorted(names)
        assert isinstance(airports[0], Airport)

    def test_get_airports_cached(self, searcher):
        with patch('flight_search.client.httpx.get') as mock_get:
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
        searcher._cache.disk.set(key, ([{"code": "VLC", "name": "Valencia"}], _time.time() - 100000), expire=700000)

        with patch('flight_search.client.httpx.get', side_effect=Exception("Network error")):
            airports = searcher.get_airports()

        assert len(airports) == 1
        assert airports[0].code == 'VLC'


class TestDataFreshness:
    def test_freshness_initial(self, searcher):
        f = searcher.get_data_freshness()
        assert f['age_minutes'] is None

    def test_freshness_after_api_call(self, searcher):
        import time as _time
        searcher._client._last_api_call_ts = _time.time()
        f = searcher.get_data_freshness()
        assert f['age_minutes'] == 0
        assert f['stale'] is False

    def test_freshness_stale_flag(self, searcher):
        import time as _time
        searcher._client._last_api_call_ts = _time.time() - 600  # 10 мин назад
        searcher._client._served_from_stale = True
        f = searcher.get_data_freshness()
        assert f['stale'] is True
        assert f['age_minutes'] == 10


# ── New coverage: one-day trips, retry policy, SWR ──────


def _make_flight(origin, dest, dep_str, arr_str, price=20.0, flight_num='FR 1'):
    return Flight(
        origin=origin, destination=dest,
        departure_time=datetime.fromisoformat(dep_str),
        arrival_time=datetime.fromisoformat(arr_str),
        flight_number=flight_num, price=price, currency='EUR',
    )


class TestOneDayTrips:
    """Tests for async_search_one_day_trips filtering logic."""

    def _run(self, searcher, morning_flights, evening_flights, destinations=None, max_price=200):
        if destinations is None:
            destinations = {'BGY': Destination(price=15, name='Milan Bergamo', country='Italy')}

        async def mock_fetch_dest(client, params):
            return destinations

        async def mock_fetch_flights(client, sem, origin, dest, name, date_out, flex_days_out=0):
            if origin == searcher.config['origin_airport']:
                return morning_flights.get(dest, [])
            return evening_flights.get(origin, [])

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, side_effect=mock_fetch_dest), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, side_effect=mock_fetch_flights):
            return searcher.search_one_day_trips(max_price_override=max_price)

    def test_morning_outbound_filter(self, searcher):
        morning = {'BGY': [
            _make_flight('VLC', 'BGY', '2026-05-25T08:00:00', '2026-05-25T10:00:00', 15, 'FR 1'),
            _make_flight('VLC', 'BGY', '2026-05-25T11:59:00', '2026-05-25T13:59:00', 15, 'FR 2'),
            _make_flight('VLC', 'BGY', '2026-05-25T12:00:00', '2026-05-25T14:00:00', 15, 'FR 3'),
            _make_flight('VLC', 'BGY', '2026-05-25T14:00:00', '2026-05-25T16:00:00', 15, 'FR 4'),
        ]}
        evening = {'BGY': [
            _make_flight('BGY', 'VLC', '2026-05-26T18:00:00', '2026-05-26T20:00:00', 15, 'FR 10'),
        ]}
        results = self._run(searcher, morning, evening)
        # Only FR 1 (08:00) and FR 2 (11:59) have dep hour < 12
        out_flights = {r.outbound.flight_number for r in results}
        assert 'FR 1' in out_flights
        assert 'FR 2' in out_flights
        assert 'FR 3' not in out_flights
        assert 'FR 4' not in out_flights

    def test_evening_return_filter(self, searcher):
        morning = {'BGY': [
            _make_flight('VLC', 'BGY', '2026-05-25T08:00:00', '2026-05-25T10:00:00', 15, 'FR 1'),
        ]}
        evening = {'BGY': [
            _make_flight('BGY', 'VLC', '2026-05-26T16:00:00', '2026-05-26T17:59:00', 15, 'FR 10'),
            _make_flight('BGY', 'VLC', '2026-05-26T19:00:00', '2026-05-26T18:00:00', 15, 'FR 11'),
            _make_flight('BGY', 'VLC', '2026-05-26T21:00:00', '2026-05-26T23:00:00', 15, 'FR 12'),
        ]}
        results = self._run(searcher, morning, evening)
        ret_flights = {r.inbound.flight_number for r in results}
        # FR 10 arrives at 17:59 → filtered out (< 18)
        assert 'FR 10' not in ret_flights
        assert 'FR 11' in ret_flights
        assert 'FR 12' in ret_flights

    def test_stay_duration_bounds(self, searcher):
        # 5h stay → rejected, 8h → accepted, 37h → rejected
        morning = {'BGY': [
            _make_flight('VLC', 'BGY', '2026-05-25T07:00:00', '2026-05-25T09:00:00', 15, 'FR 1'),
        ]}
        evening = {'BGY': [
            _make_flight('BGY', 'VLC', '2026-05-25T13:00:00', '2026-05-25T19:00:00', 15, 'FR A'),  # 4h stay - same day skip
            _make_flight('BGY', 'VLC', '2026-05-26T02:00:00', '2026-05-26T18:00:00', 15, 'FR B'),  # 17h stay
            _make_flight('BGY', 'VLC', '2026-05-26T22:00:00', '2026-05-26T23:59:00', 15, 'FR C'),  # 37h stay
        ]}
        results = self._run(searcher, morning, evening)
        ret_flights = {r.inbound.flight_number for r in results}
        assert 'FR B' in ret_flights  # 17h within [6, 36]
        assert 'FR C' not in ret_flights  # 37h > 36

    def test_same_day_skip(self, searcher):
        morning = {'BGY': [
            _make_flight('VLC', 'BGY', '2026-05-25T07:00:00', '2026-05-25T09:00:00', 15, 'FR 1'),
        ]}
        evening = {'BGY': [
            _make_flight('BGY', 'VLC', '2026-05-25T20:00:00', '2026-05-25T22:00:00', 15, 'FR 10'),
        ]}
        results = self._run(searcher, morning, evening)
        # outbound dep date == inbound arrival date → skipped
        assert len(results) == 0

    def test_max_price_filter(self, searcher):
        morning = {'BGY': [
            _make_flight('VLC', 'BGY', '2026-05-25T08:00:00', '2026-05-25T10:00:00', 50, 'FR 1'),
        ]}
        evening = {'BGY': [
            _make_flight('BGY', 'VLC', '2026-05-26T19:00:00', '2026-05-26T21:00:00', 60, 'FR 10'),
        ]}
        results = self._run(searcher, morning, evening, max_price=100)
        assert len(results) == 0  # 50+60=110 > 100


class TestRetryPolicy:
    """Tests for _is_retryable function."""

    def test_retryable_errors(self):
        assert _is_retryable(httpx.TimeoutException("timeout")) is True
        assert _is_retryable(httpx.ConnectError("conn")) is True

        for status in (429, 500, 502, 503, 504):
            req = httpx.Request("GET", "http://test")
            resp = httpx.Response(status, request=req)
            exc = httpx.HTTPStatusError("err", request=req, response=resp)
            assert _is_retryable(exc) is True, f"status {status} should be retryable"

    def test_non_retryable_errors(self):
        for status in (400, 404, 403):
            req = httpx.Request("GET", "http://test")
            resp = httpx.Response(status, request=req)
            exc = httpx.HTTPStatusError("err", request=req, response=resp)
            assert _is_retryable(exc) is False, f"status {status} should not be retryable"

        assert _is_retryable(ValueError("bad")) is False


class TestFetchDestinationsSWR:
    """Tests for SWR caching in fetch_destinations."""

    def _cache_key(self, searcher):
        return searcher._cache.key("dest", "VLC", "2026-05-20", "2026-05-22")

    def _dest_data(self):
        return {'BGY': {'price': 15.0, 'name': 'Milan Bergamo', 'country': 'Italy'}}

    def test_fresh_cache_no_api(self, searcher):
        key = self._cache_key(searcher)
        searcher._cache.set(key, self._dest_data(), TTL_DESTINATIONS[1])

        with patch.object(searcher._client, '_refresh_destinations', new_callable=AsyncMock) as mock_refresh:
            result = searcher.get_available_destinations('2026-05-20', '2026-05-22')

        assert not mock_refresh.called
        assert 'BGY' in result

    def test_stale_triggers_refresh(self, searcher):
        key = self._cache_key(searcher)
        # Insert stale data
        searcher._cache.disk.set(key, (self._dest_data(), _time.time() - 2000), expire=TTL_DESTINATIONS[1])
        searcher._cache.l1.clear()

        new_data = {'MXP': Destination(price=25, name='Milan Malpensa', country='Italy')}

        with patch.object(searcher._client, '_refresh_destinations', new_callable=AsyncMock, return_value=new_data):
            result = searcher.get_available_destinations('2026-05-20', '2026-05-22')

        assert 'MXP' in result

    def test_error_stale_fallback(self, searcher):
        key = self._cache_key(searcher)
        searcher._cache.disk.set(key, (self._dest_data(), _time.time() - 2000), expire=TTL_DESTINATIONS[1])
        searcher._cache.l1.clear()

        with patch.object(searcher._client, '_refresh_destinations', new_callable=AsyncMock,
                          side_effect=httpx.ConnectError("down")):
            result = searcher.get_available_destinations('2026-05-20', '2026-05-22')

        assert 'BGY' in result
        assert searcher._client._served_from_stale is True


class TestFetchFlightsDirect:
    """Direct unit tests for fetch_flights SWR caching."""

    def _cache_key(self, searcher):
        return searcher._cache.key("flights", "VLC", "BGY", "2026-05-20", 0)

    def _flight_data(self):
        f = _make_flight('VLC', 'BGY', '2026-05-20T10:00:00', '2026-05-20T12:00:00', 25.0, 'FR 123')
        return [f.model_dump(mode='json')]

    def test_fresh_cache_no_api(self, searcher):
        key = self._cache_key(searcher)
        searcher._cache.set(key, self._flight_data(), TTL_FLIGHTS[1])

        import asyncio
        with patch.object(searcher._client, '_refresh_flights', new_callable=AsyncMock) as mock_refresh:
            async def _run():
                sem = asyncio.Semaphore(1)
                return await searcher._client.fetch_flights(
                    MagicMock(), sem, 'VLC', 'BGY', 'Milan Bergamo', '2026-05-20')
            result = asyncio.run(_run())

        assert not mock_refresh.called
        assert len(result) == 1
        assert result[0].flight_number == 'FR 123'

    def test_cache_miss_calls_api(self, searcher):
        import asyncio
        new_flights = [_make_flight('VLC', 'BGY', '2026-05-20T10:00:00', '2026-05-20T12:00:00', 30.0, 'FR 999')]

        with patch.object(searcher._client, '_refresh_flights', new_callable=AsyncMock, return_value=new_flights) as mock_refresh:
            async def _run():
                sem = asyncio.Semaphore(1)
                return await searcher._client.fetch_flights(
                    MagicMock(), sem, 'VLC', 'BGY', 'Milan Bergamo', '2026-05-20')
            result = asyncio.run(_run())

        assert mock_refresh.called
        assert result[0].flight_number == 'FR 999'

    def test_stale_triggers_refresh(self, searcher):
        key = self._cache_key(searcher)
        searcher._cache.disk.set(key, (self._flight_data(), _time.time() - 400), expire=TTL_FLIGHTS[1])
        searcher._cache.l1.clear()

        import asyncio
        new_flights = [_make_flight('VLC', 'BGY', '2026-05-20T14:00:00', '2026-05-20T16:00:00', 35.0, 'FR 777')]

        with patch.object(searcher._client, '_refresh_flights', new_callable=AsyncMock, return_value=new_flights):
            async def _run():
                sem = asyncio.Semaphore(1)
                return await searcher._client.fetch_flights(
                    MagicMock(), sem, 'VLC', 'BGY', 'Milan Bergamo', '2026-05-20')
            result = asyncio.run(_run())

        assert result[0].flight_number == 'FR 777'

    def test_error_stale_fallback(self, searcher):
        key = self._cache_key(searcher)
        searcher._cache.disk.set(key, (self._flight_data(), _time.time() - 400), expire=TTL_FLIGHTS[1])
        searcher._cache.l1.clear()

        import asyncio
        with patch.object(searcher._client, '_refresh_flights', new_callable=AsyncMock,
                          side_effect=httpx.ConnectError("down")):
            async def _run():
                sem = asyncio.Semaphore(1)
                return await searcher._client.fetch_flights(
                    MagicMock(), sem, 'VLC', 'BGY', 'Milan Bergamo', '2026-05-20')
            result = asyncio.run(_run())

        assert len(result) == 1
        assert result[0].flight_number == 'FR 123'
        assert searcher._client._served_from_stale is True


class TestHopsValidation:
    """Tests for hops clamping in search_nomad_routes."""

    def test_hops_0_clamped_to_1(self, searcher):
        with patch.object(searcher, 'async_search_nomad_routes', new_callable=AsyncMock, return_value=[]) as mock:
            searcher.search_nomad_routes(origin='VLC', departure_date='2026-05-19', hops=0)
        assert mock.call_args[0][2] == 1

    def test_hops_5_clamped_to_4(self, searcher):
        with patch.object(searcher, 'async_search_nomad_routes', new_callable=AsyncMock, return_value=[]) as mock:
            searcher.search_nomad_routes(origin='VLC', departure_date='2026-05-19', hops=5)
        assert mock.call_args[0][2] == 4

    def test_hops_2_unchanged(self, searcher):
        with patch.object(searcher, 'async_search_nomad_routes', new_callable=AsyncMock, return_value=[]) as mock:
            searcher.search_nomad_routes(origin='VLC', departure_date='2026-05-19', hops=2)
        assert mock.call_args[0][2] == 2


class TestClientLifecycle:
    """Tests for RyanairClient open/close."""

    def test_open_creates_client(self, searcher):
        import asyncio
        assert searcher._client._client is None
        asyncio.run(searcher._client.open())
        assert searcher._client._client is not None
        asyncio.run(searcher._client.close())
        assert searcher._client._client is None

    def test_close_idempotent(self, searcher):
        import asyncio
        asyncio.run(searcher._client.close())  # no client yet
        asyncio.run(searcher._client.open())
        asyncio.run(searcher._client.close())
        asyncio.run(searcher._client.close())  # second close
        assert searcher._client._client is None


class TestRandomHeaders:
    def test_returns_user_agent(self, searcher):
        headers = searcher._client._get_random_headers()
        assert isinstance(headers, dict)
        assert 'User-Agent' in headers
        assert headers['User-Agent'] in searcher._client.USER_AGENTS


class TestLoggingConfig:
    def test_setup_does_not_crash(self):
        from logging_config import setup_logging
        setup_logging()
        setup_logging("DEBUG")


class TestPrintResults:
    def test_print_results_empty(self, searcher):
        searcher.print_results([], nights=1)

    def test_print_one_day_empty(self, searcher):
        searcher.print_one_day_results([])
