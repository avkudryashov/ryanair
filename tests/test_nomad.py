"""Тесты nomad-режима: backend API фильтрация по датам и ценам."""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from flight_search import FlightSearcher
from models import Flight, Destination


def make_flight(origin, dest, dest_name, dep_str, arr_str, price, flight_num, country='Italy'):
    """Хелпер: создаёт Flight в формате _parse_flights."""
    return Flight(
        origin=origin,
        origin_name=origin,
        destination=dest,
        destination_name=dest_name,
        departure_time=datetime.fromisoformat(dep_str),
        arrival_time=datetime.fromisoformat(arr_str),
        flight_number=flight_num,
        price=price,
        currency='EUR',
    )



class TestNomadDateFiltering:
    """Проверяем что рейсы за пределами date_from..date_to отфильтровываются."""

    def test_single_day_filters_out_next_day(self, searcher):
        """date_from == date_to == May 18 → рейс на May 19 ДОЛЖЕН быть отфильтрован."""
        flights_may18 = [
            make_flight('VLC', 'PMO', 'Palermo', '2026-05-18T05:50:00', '2026-05-18T07:55:00', 16.0, 'FR 7548'),
        ]
        flights_may19 = [
            make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T05:50:00', '2026-05-19T07:55:00', 16.0, 'FR 7548'),
        ]

        destinations = {'PMO': Destination(name='Palermo', country='Italy', price=16.0)}

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights_may18 + flights_may19):
            results = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=100, top_n=20,
            )

            dates = [r['departure_time'][:10] for r in results]
            assert '2026-05-18' in dates, "Рейс на May 18 должен присутствовать"
            assert '2026-05-19' not in dates, "Рейс на May 19 должен быть отфильтрован (date_to=May 18)"

    def test_range_filters_correctly(self, searcher):
        """date_from=May 21, date_to=May 21 (2 ночи после прилёта 19) → только May 21."""
        flights = [
            make_flight('PMO', 'CTA', 'Catania', '2026-05-20T10:00:00', '2026-05-20T11:00:00', 15.0, 'FR 3735'),
            make_flight('PMO', 'CTA', 'Catania', '2026-05-21T10:00:00', '2026-05-21T11:00:00', 15.0, 'FR 3736'),
            make_flight('PMO', 'CTA', 'Catania', '2026-05-22T10:00:00', '2026-05-22T11:00:00', 15.0, 'FR 3737'),
        ]

        destinations = {'CTA': Destination(name='Catania', country='Italy', price=15.0)}

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):

            results = searcher.search_nomad_options(
                origin='PMO', date_from='2026-05-21', date_to='2026-05-21',
                max_price_per_leg=100, top_n=20,
            )

            dates = [r['departure_time'][:10] for r in results]
            assert dates == ['2026-05-21'], f"Должен быть только May 21, получили: {dates}"

    def test_two_night_stay_range(self, searcher):
        """Ночи=[2,3] → date_from=arrival+2, date_to=arrival+3. Проверяем диапазон."""
        flights = [
            make_flight('PMO', 'MLA', 'Malta', '2026-05-20T12:00:00', '2026-05-20T13:00:00', 15.0, 'FR 5970'),
            make_flight('PMO', 'MLA', 'Malta', '2026-05-21T12:00:00', '2026-05-21T13:00:00', 15.0, 'FR 5971'),
            make_flight('PMO', 'MLA', 'Malta', '2026-05-22T12:00:00', '2026-05-22T13:00:00', 15.0, 'FR 5972'),
            make_flight('PMO', 'MLA', 'Malta', '2026-05-23T12:00:00', '2026-05-23T13:00:00', 15.0, 'FR 5973'),
        ]
        # Прилёт в PMO: May 19. nights=[2,3] → min=2, max=3 → date_from=May 21, date_to=May 22
        destinations = {'MLA': Destination(name='Malta', country='Malta', price=15.0)}

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):

            results = searcher.search_nomad_options(
                origin='PMO', date_from='2026-05-21', date_to='2026-05-22',
                max_price_per_leg=100, top_n=20,
            )

            dates = sorted([r['departure_time'][:10] for r in results])
            assert '2026-05-20' not in dates, "May 20 вне диапазона"
            assert '2026-05-21' in dates, "May 21 в диапазоне"
            assert '2026-05-22' in dates, "May 22 в диапазоне"
            assert '2026-05-23' not in dates, "May 23 вне диапазона"


class TestNomadPriceFiltering:
    """Проверяем фильтрацию по цене."""

    def test_max_price_filters(self, searcher):
        flights = [
            make_flight('VLC', 'PMO', 'Palermo', '2026-05-18T10:00:00', '2026-05-18T12:00:00', 16.0, 'FR 7548'),
            make_flight('VLC', 'BGY', 'Bergamo', '2026-05-18T14:00:00', '2026-05-18T16:00:00', 55.0, 'FR 1234'),
        ]
        destinations = {
            'PMO': Destination(name='Palermo', country='Italy', price=16.0),
            'BGY': Destination(name='Bergamo', country='Italy', price=55.0),
        }

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):

            results = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=50, top_n=20,
            )

            prices = [r['price'] for r in results]
            assert 16.0 in prices
            assert 55.0 not in prices, "Рейс за 55 EUR должен быть отфильтрован (max=50)"


class TestNomadTopN:
    """Проверяем лимит top_n."""

    def test_top_n_limits_results(self, searcher):
        flights = [
            make_flight('VLC', f'D{i:02d}', f'Dest{i}', f'2026-05-18T{10+i%12}:00:00', f'2026-05-18T{11+i%12}:00:00', 10.0 + i, f'FR {i}')
            for i in range(20)
        ]
        destinations = {f'D{i:02d}': Destination(name=f'Dest{i}', country='Test', price=10.0 + i) for i in range(20)}

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):

            results = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=100, top_n=5,
            )

            assert len(results) == 5
            # Должны быть отсортированы по цене
            prices = [r['price'] for r in results]
            assert prices == sorted(prices)


class TestNomadExclusions:
    """Проверяем исключение аэропортов и стран."""

    def test_excluded_airports(self, searcher):
        flights_bgy = [make_flight('VLC', 'BGY', 'Bergamo', '2026-05-18T14:00:00', '2026-05-18T16:00:00', 20.0, 'FR 1234')]
        destinations = {
            'PMO': Destination(name='Palermo', country='Italy', price=16.0),
            'BGY': Destination(name='Bergamo', country='Italy', price=55.0),
        }

        # fetch_flights returns only BGY flights — PMO excluded at destinations level
        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights_bgy):

            results = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=100, top_n=20,
                excluded_airports=['PMO'],
            )

            dests = [r['destination'] for r in results]
            assert 'PMO' not in dests

    def test_excluded_countries(self, searcher):
        destinations = {
            'PMO': Destination(name='Palermo', country='Italy', price=16.0),
            'LIS': Destination(name='Lisbon', country='Portugal', price=15.0),
        }

        # Мокаем _fetch_destinations чтобы вернуть обе страны
        # А потом проверяем что Italy исключена
        async def mock_fetch_flights(*args, **kwargs):
            return [make_flight('VLC', 'LIS', 'Lisbon', '2026-05-18T10:00:00', '2026-05-18T12:00:00', 15.0, 'FR 999')]

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', side_effect=mock_fetch_flights):

            results = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=100, top_n=20,
                excluded_countries=['Italy'],
            )

            countries = [r['country'] for r in results]
            assert 'Italy' not in countries


class TestNomadTimezoneEdgeCases:
    """Рейсы с timezone — проверяем что .date() не ломается."""

    def test_late_night_flight_timezone_aware(self, searcher):
        """Рейс в 23:20 local (UTC+2) — .date() должен вернуть ту же дату, не предыдущую."""
        flights = [
            make_flight('VLC', 'PMO', 'Palermo',
                        '2026-05-18T23:20:00+02:00', '2026-05-19T01:30:00+02:00', 16.0, 'FR 7548'),
            make_flight('VLC', 'BGY', 'Bergamo',
                        '2026-05-19T23:20:00+02:00', '2026-05-20T01:30:00+02:00', 20.0, 'FR 1234'),
        ]
        destinations = {
            'PMO': Destination(name='Palermo', country='Italy', price=16.0),
            'BGY': Destination(name='Bergamo', country='Italy', price=55.0),
        }

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):

            results = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=100, top_n=20,
            )

            dates = [r['departure_time'][:10] for r in results]
            assert '2026-05-18' in dates, "Рейс 18 мая 23:20+02:00 должен остаться"
            assert '2026-05-19' not in dates, "Рейс 19 мая должен быть отфильтрован"


class TestNomadEndToEndScenario:
    """E2E сценарий: VLC → PMO (May 18), 2 ночи → рейс из PMO на May 20 только."""

    def test_full_scenario_two_nights(self, searcher):
        """
        Сценарий:
        1. Пользователь ставит дату=May 18, ночей=2
        2. Frontend: root date_from=date_to=May 18
        3. Пользователь выбирает VLC→PMO, прилёт May 18
        4. Frontend: child date_from=date_to=May 20 (arrival + 2 ночи)
        5. Backend должен вернуть ТОЛЬКО рейсы на May 20
        """
        # Шаг 1: рейсы из VLC на 18 мая
        vlc_flights = [
            make_flight('VLC', 'PMO', 'Palermo', '2026-05-18T05:50:00', '2026-05-18T07:55:00', 16.0, 'FR 7548'),
            make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T05:50:00', '2026-05-19T07:55:00', 16.0, 'FR 7549'),  # wrong date
        ]
        vlc_destinations = {'PMO': Destination(name='Palermo', country='Italy', price=16.0)}

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=vlc_destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=vlc_flights):

            step1 = searcher.search_nomad_options(
                origin='VLC', date_from='2026-05-18', date_to='2026-05-18',
                max_price_per_leg=100, top_n=20,
            )

        step1_dates = [r['departure_time'][:10] for r in step1]
        assert step1_dates == ['2026-05-18'], f"Шаг 1: только May 18, получили {step1_dates}"

        # Шаг 2: рейсы из PMO — прилёт May 18, 2 ночи → ищем May 20
        pmo_flights = [
            make_flight('PMO', 'CTA', 'Catania', '2026-05-19T10:00:00', '2026-05-19T11:00:00', 15.0, 'FR 3735'),  # May 19 - too early
            make_flight('PMO', 'MLA', 'Malta', '2026-05-20T12:00:00', '2026-05-20T13:00:00', 15.0, 'FR 5970'),    # May 20 - correct
            make_flight('PMO', 'CTA', 'Catania', '2026-05-20T23:15:00', '2026-05-21T01:15:00', 15.0, 'FR 3736'),  # May 20 - correct
            make_flight('PMO', 'BRU', 'Brussels', '2026-05-21T07:30:00', '2026-05-21T10:55:00', 30.0, 'FR 2929'), # May 21 - too late
        ]
        pmo_destinations = {
            'CTA': Destination(name='Catania', country='Italy', price=15.0),
            'MLA': Destination(name='Malta', country='Malta', price=15.0),
            'BRU': Destination(name='Brussels', country='Belgium', price=15.0),
        }

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=pmo_destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=pmo_flights):

            # Frontend вычислит: arrival=May 18, nights=2 → date_from=date_to=May 20
            step2 = searcher.search_nomad_options(
                origin='PMO', date_from='2026-05-20', date_to='2026-05-20',
                max_price_per_leg=100, top_n=20,
            )

        step2_dates = [r['departure_time'][:10] for r in step2]
        assert all(d == '2026-05-20' for d in step2_dates), \
            f"Шаг 2: только May 20 (2 ночи после прилёта May 18), получили {step2_dates}"
        assert len(step2) == 2, f"Должно быть 2 рейса на May 20, получили {len(step2)}"


class TestNomadOriginIsolation:
    """Проверяем что origin передаётся явно и не мутирует self.origin (race condition fix)."""

    def test_origin_not_mutated(self, searcher):
        """search_nomad_options НЕ должен менять self.origin."""
        searcher.origin = 'ORIGINAL'
        destinations = {'PMO': Destination(name='Palermo', country='Italy', price=16.0)}
        flights = [make_flight('TSF', 'PMO', 'Palermo', '2026-05-21T10:00:00', '2026-05-21T12:00:00', 15.0, 'FR 100')]

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):

            searcher.search_nomad_options(
                origin='TSF', date_from='2026-05-21', date_to='2026-05-21',
                max_price_per_leg=100, top_n=20,
            )

        assert searcher.origin == 'ORIGINAL', "self.origin не должен быть изменён"

    def test_different_origins_get_different_params(self, searcher):
        """Два вызова с разными origin должны передавать правильный origin в _fetch_flights."""
        origins_used = []
        destinations = {'PMO': Destination(name='Palermo', country='Italy', price=16.0)}

        async def mock_fetch_flights(client, sem, origin, dest, name, date_out, flex_days_out=0):
            origins_used.append(origin)
            return [make_flight(origin, dest, name, '2026-05-21T10:00:00', '2026-05-21T12:00:00', 15.0, 'FR 100')]

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=destinations), \
             patch.object(searcher._client, 'fetch_flights', side_effect=mock_fetch_flights):

            searcher.search_nomad_options(origin='TSF', date_from='2026-05-21', date_to='2026-05-21',
                                          max_price_per_leg=100, top_n=20)
            searcher.search_nomad_options(origin='PMO', date_from='2026-05-21', date_to='2026-05-21',
                                          max_price_per_leg=100, top_n=20)

        assert 'TSF' in origins_used, "Должен быть вызов с origin=TSF"
        assert 'PMO' in origins_used, "Должен быть вызов с origin=PMO"

    def test_return_origin_not_mutated(self, searcher):
        """search_nomad_return НЕ должен менять self.origin."""
        searcher.origin = 'ORIGINAL'
        flights = [make_flight('PMO', 'VLC', 'Valencia', '2026-05-23T10:00:00', '2026-05-23T12:00:00', 20.0, 'FR 200')]

        with patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=flights):
            searcher.search_nomad_return(
                origin='PMO', destination='VLC',
                date_from='2026-05-23', date_to='2026-05-23', max_price=100,
            )

        assert searcher.origin == 'ORIGINAL', "self.origin не должен быть изменён"


class TestBuildDateBatches:
    """Тесты _build_date_batches — критичны для правильного запроса к API."""

    def test_same_day(self, searcher):
        """date_from == date_to → один батч с flex=0."""
        batches = searcher._client.build_date_batches('2026-05-18', '2026-05-18')
        assert batches == [('2026-05-18', 0)]

    def test_two_day_range(self, searcher):
        batches = searcher._client.build_date_batches('2026-05-18', '2026-05-19')
        assert batches == [('2026-05-18', 1)]

    def test_large_range_splits(self, searcher):
        batches = searcher._client.build_date_batches('2026-05-01', '2026-05-20')
        # 19 days total, MAX_FLEX_DAYS=6 → splits into batches
        assert len(batches) > 1
        # Проверяем покрытие всех дат
        for batch_date, flex in batches:
            assert flex <= searcher._client.MAX_FLEX_DAYS


# ── P1: Nomad Routes Algorithm ──────────────────────────────

def make_returnable_destinations(codes_with_info):
    """Helper: dict of {code: {name, country}} for returnable set."""
    return {c: Destination(name=n, country=co, price=20.0) for c, n, co in codes_with_info}


class TestReturnableSet:
    """P1.1: Returnable set calculation."""

    def test_returnable_set_computed_from_origin(self, searcher):
        """_fetch_destinations called with origin to compute returnable airports."""
        dests_origin = {'PMO': Destination(name='Palermo', country='Italy', price=16.0),
                        'BGY': Destination(name='Milan Bergamo', country='Italy', price=20.0)}
        flight_pmo = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 20.0, 'FR 100')
        flight_ret = make_flight('PMO', 'VLC', 'Valencia', '2026-05-21T18:00:00', '2026-05-21T20:00:00', 20.0, 'FR 200')

        fetch_dest_calls = []
        async def mock_fetch_dest(client, params):
            fetch_dest_calls.append(params['departureAirportIataCode'])
            return dests_origin

        with patch.object(searcher._client, 'fetch_destinations', side_effect=mock_fetch_dest), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=[flight_pmo, flight_ret]):
            results = searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
            )

        assert 'VLC' in fetch_dest_calls, "Must call _fetch_destinations with origin for returnable set"

    def test_returnable_set_filters_excluded(self, searcher):
        """Excluded airports/countries removed from returnable set."""
        dests = {'PMO': Destination(name='Palermo', country='Italy', price=16.0),
                 'AGP': Destination(name='Malaga', country='Spain', price=15.0)}
        flight_pmo = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 20.0, 'FR 100')
        flight_ret = make_flight('PMO', 'VLC', 'Valencia', '2026-05-21T18:00:00', '2026-05-21T20:00:00', 20.0, 'FR 200')

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=dests), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=[flight_pmo, flight_ret]):
            results = searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
                excluded_countries=['Spain'],
            )

        dest_codes = [r['legs'][0]['destination'] for r in results]
        assert 'AGP' not in dest_codes, "Excluded country airports should be filtered"

    def test_empty_returnable_set_returns_empty(self, searcher):
        """No returnable airports → empty results."""
        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value={}):
            results = searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
            )
        assert results == []


class TestNomadRoutesSingleHop:
    """P1.2: Single-hop (hops=1) — round trip."""

    def _run_single_hop(self, searcher, nights=[2]):
        dests = {'PMO': Destination(name='Palermo', country='Italy', price=16.0),
                 'BGY': Destination(name='Milan Bergamo', country='Italy', price=20.0)}
        outbound = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 20.0, 'FR 100')
        ret_flight = make_flight('PMO', 'VLC', 'Valencia', '2026-05-21T18:00:00', '2026-05-21T20:00:00', 15.0, 'FR 200')

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=dests), \
             patch.object(searcher._client, 'fetch_flights', new_callable=AsyncMock, return_value=[outbound, ret_flight]):
            return searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=nights, max_price_per_leg=100, top_n=10,
            )

    def test_single_hop_includes_return_flight(self, searcher):
        results = self._run_single_hop(searcher)
        assert len(results) > 0
        assert 'return_flight' in results[0]
        assert results[0]['return_flight']['flight_number'] == 'FR 200'

    def test_single_hop_total_price_includes_return(self, searcher):
        results = self._run_single_hop(searcher)
        assert results[0]['total_price'] == 35.0  # 20 outbound + 15 return

    def test_single_hop_route_structure(self, searcher):
        results = self._run_single_hop(searcher)
        r = results[0]
        assert r['origin'] == 'VLC'
        assert len(r['legs']) == 1
        assert r['legs'][0]['destination'] == 'PMO'


class TestNomadRoutesMultiHop:
    """P1.3: Multi-hop (hops=2)."""

    def _setup_two_hop(self, searcher):
        """Sets up: VLC → PMO → BGY → VLC."""
        dests_vlc = {'PMO': Destination(name='Palermo', country='Italy', price=16.0),
                     'BGY': Destination(name='Milan Bergamo', country='Italy', price=20.0)}
        dests_pmo = {'BGY': Destination(name='Milan Bergamo', country='Italy', price=20.0),
                     'CTA': Destination(name='Catania', country='Italy', price=15.0)}

        hop1 = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 15.0, 'FR 100')
        hop2_bgy = make_flight('PMO', 'BGY', 'Milan Bergamo', '2026-05-21T10:00:00', '2026-05-21T12:00:00', 20.0, 'FR 200')
        hop2_cta = make_flight('PMO', 'CTA', 'Catania', '2026-05-21T10:00:00', '2026-05-21T11:00:00', 10.0, 'FR 300')
        ret_bgy = make_flight('BGY', 'VLC', 'Valencia', '2026-05-23T18:00:00', '2026-05-23T20:00:00', 25.0, 'FR 400')
        ret_cta = make_flight('CTA', 'VLC', 'Valencia', '2026-05-23T18:00:00', '2026-05-23T20:00:00', 30.0, 'FR 500')

        call_count = [0]
        async def mock_fetch_dest(client, params):
            call_count[0] += 1
            airport = params['departureAirportIataCode']
            if airport == 'VLC':
                return dests_vlc
            elif airport == 'PMO':
                return dests_pmo
            return {}

        async def mock_fetch_flights(client, sem, origin, dest, name, date_out, flex_days_out=0):
            if origin == 'VLC' and dest == 'PMO':
                return [hop1]
            if origin == 'PMO' and dest == 'BGY':
                return [hop2_bgy]
            if origin == 'PMO' and dest == 'CTA':
                return [hop2_cta]
            if origin == 'BGY' and dest == 'VLC':
                return [ret_bgy]
            if origin == 'CTA' and dest == 'VLC':
                return [ret_cta]
            return []

        with patch.object(searcher._client, 'fetch_destinations', side_effect=mock_fetch_dest), \
             patch.object(searcher._client, 'fetch_flights', side_effect=mock_fetch_flights):
            return searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=2,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
            )

    def test_two_hop_builds_correct_route(self, searcher):
        results = self._setup_two_hop(searcher)
        assert len(results) > 0
        r = results[0]
        assert len(r['legs']) == 2
        assert r['origin'] == 'VLC'
        assert r['return_flight'] is not None

    def test_two_hop_last_hop_filtered_by_returnable(self, searcher):
        """Second city must be in returnable_set (airports VLC flies to)."""
        results = self._setup_two_hop(searcher)
        for r in results:
            last_dest = r['legs'][-1]['destination']
            # Both BGY and CTA are in returnable set (VLC flies to both)
            assert last_dest in ('BGY', 'CTA')

    def test_two_hop_no_revisit(self, searcher):
        """Can't visit same city twice."""
        results = self._setup_two_hop(searcher)
        for r in results:
            cities = [l['destination'] for l in r['legs']]
            assert len(cities) == len(set(cities)), f"Duplicate city in route: {cities}"

    def test_two_hop_stay_nights_assigned(self, searcher):
        results = self._setup_two_hop(searcher)
        for r in results:
            for leg in r['legs']:
                assert 'stay_nights' in leg
                assert leg['stay_nights'] > 0


class TestNomadReturnValidation:
    """P1.4: Return flight validation."""

    def test_no_return_flight_discards_route(self, searcher):
        """Route to airport with no return should be discarded."""
        dests = {'PMO': Destination(name='Palermo', country='Italy', price=16.0)}
        outbound = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 20.0, 'FR 100')

        call_count = [0]
        async def mock_fetch_flights(client, sem, origin, dest, name, date_out, flex_days_out=0):
            call_count[0] += 1
            if origin == 'VLC':
                return [outbound]
            return []  # No return flights

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=dests), \
             patch.object(searcher._client, 'fetch_flights', side_effect=mock_fetch_flights):
            results = searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
            )
        assert results == [], "Routes without return should be discarded"

    def test_cheapest_return_selected(self, searcher):
        dests = {'PMO': Destination(name='Palermo', country='Italy', price=16.0)}
        outbound = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 20.0, 'FR 100')
        ret_cheap = make_flight('PMO', 'VLC', 'Valencia', '2026-05-21T18:00:00', '2026-05-21T20:00:00', 10.0, 'FR 200')
        ret_expensive = make_flight('PMO', 'VLC', 'Valencia', '2026-05-21T20:00:00', '2026-05-21T22:00:00', 50.0, 'FR 201')

        async def mock_fetch_flights(client, sem, origin, dest, name, date_out, flex_days_out=0):
            if origin == 'VLC':
                return [outbound]
            return [ret_cheap, ret_expensive]

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=dests), \
             patch.object(searcher._client, 'fetch_flights', side_effect=mock_fetch_flights):
            results = searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
            )
        assert results[0]['return_flight']['price'] == 10.0

    def test_routes_sorted_by_total_price(self, searcher):
        dests = {'PMO': Destination(name='Palermo', country='Italy', price=16.0),
                 'BGY': Destination(name='Milan Bergamo', country='Italy', price=20.0)}
        out_pmo = make_flight('VLC', 'PMO', 'Palermo', '2026-05-19T10:00:00', '2026-05-19T12:00:00', 30.0, 'FR 100')
        out_bgy = make_flight('VLC', 'BGY', 'Milan Bergamo', '2026-05-19T08:00:00', '2026-05-19T10:00:00', 10.0, 'FR 101')
        ret_pmo = make_flight('PMO', 'VLC', 'Valencia', '2026-05-21T18:00:00', '2026-05-21T20:00:00', 20.0, 'FR 200')
        ret_bgy = make_flight('BGY', 'VLC', 'Valencia', '2026-05-21T18:00:00', '2026-05-21T20:00:00', 15.0, 'FR 201')

        async def mock_fetch_flights(client, sem, origin, dest, name, date_out, flex_days_out=0):
            if origin == 'VLC' and dest == 'PMO': return [out_pmo]
            if origin == 'VLC' and dest == 'BGY': return [out_bgy]
            if origin == 'PMO': return [ret_pmo]
            if origin == 'BGY': return [ret_bgy]
            return []

        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value=dests), \
             patch.object(searcher._client, 'fetch_flights', side_effect=mock_fetch_flights):
            results = searcher.search_nomad_routes(
                origin='VLC', departure_date='2026-05-19', hops=1,
                nights_per_city=[2], max_price_per_leg=100, top_n=10,
            )
        prices = [r['total_price'] for r in results]
        assert prices == sorted(prices), f"Routes should be sorted by price, got {prices}"


class TestNomadRoutesEdgeCases:
    """P1.5: Edge cases."""

    def test_hops_clamped_to_1_4(self, searcher):
        """hops=0 → 1, hops=5 → 4."""
        with patch.object(searcher._client, 'fetch_destinations', new_callable=AsyncMock, return_value={}):
            # hops=0 should be clamped to 1 and return empty (no destinations)
            r1 = searcher.search_nomad_routes(origin='VLC', departure_date='2026-05-19', hops=0)
            r2 = searcher.search_nomad_routes(origin='VLC', departure_date='2026-05-19', hops=5)
        assert r1 == []
        assert r2 == []
