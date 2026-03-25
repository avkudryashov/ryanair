"""Тесты FastAPI-приложения."""
import asyncio
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from tests.conftest import AIRPORTS_RESPONSE
from models import Airport, Destination, Flight, Trip


MOCK_AIRPORTS = [
    Airport(code='VLC', name='Valencia', city='Valencia', country='Spain',
            country_code='es', schengen=True, lat=0, lng=0),
    Airport(code='BGY', name='Milan Bergamo', city='Bergamo', country='Italy',
            country_code='it', schengen=True, lat=0, lng=0),
]


@pytest.fixture
def client():
    """FastAPI test client with mocked searcher via app.state."""
    mock_searcher = MagicMock()
    mock_searcher.get_airports.return_value = MOCK_AIRPORTS
    mock_searcher.config = {'max_price': 100, 'origin_airport': 'VLC', 'currency': 'EUR'}
    mock_searcher.open = AsyncMock()
    mock_searcher.close = AsyncMock()
    mock_searcher.async_get_available_destinations = AsyncMock(return_value={})

    from app import app
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as c:
        # Override AFTER lifespan so our mocks aren't overwritten
        app.state.searcher = mock_searcher
        app.state.airports = MOCK_AIRPORTS
        app.state.countries = ['Italy', 'Spain']
        app.state.country_to_airports = {'Spain': ['VLC'], 'Italy': ['BGY']}
        app.state.airport_coords = {
            'VLC': {'lat': 0, 'lng': 0},
            'BGY': {'lat': 0, 'lng': 0},
        }
        yield c, mock_searcher


class TestIndexPage:
    def test_index_returns_200(self, client):
        c, _ = client
        resp = c.get('/')
        assert resp.status_code == 200

    def test_index_contains_form(self, client):
        c, _ = client
        resp = c.get('/')
        html = resp.text
        assert 'search-form' in html
        assert 'departure_date' in html

    def test_index_contains_airports(self, client):
        c, _ = client
        resp = c.get('/')
        html = resp.text
        assert 'VLC' in html
        assert 'Valencia' in html


class TestSearchRegular:
    def test_search_returns_results(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[Trip(
            total_price=45.0,
            outbound=Flight(
                origin='VLC', destination='BGY', destination_name='Milan Bergamo',
                departure_time=datetime(2026, 5, 20, 10, 0),
                arrival_time=datetime(2026, 5, 20, 12, 0),
                flight_number='FR 123', price=20.0, currency='EUR',
            ),
            inbound=Flight(
                origin='BGY', destination='VLC',
                departure_time=datetime(2026, 5, 21, 18, 0),
                arrival_time=datetime(2026, 5, 21, 20, 0),
                flight_number='FR 456', price=25.0, currency='EUR',
            ),
            nights=1,
            stay_duration_hours=30.0,
        )])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        resp = c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=100')
        html = resp.text
        assert resp.status_code == 200
        assert '45.0' in html
        assert 'Milan Bergamo' in html

    def test_search_missing_date_shows_error(self, client):
        c, _ = client
        resp = c.get('/?mode=regular&nights=1')
        html = resp.text
        assert resp.status_code == 200
        assert 'alert-error' in html

    def test_search_passes_excluded_countries(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&excl_countries=Spain,Italy&max_price=100')
        call_kwargs = mock.async_search_flights.call_args[1]
        assert 'Spain' in call_kwargs['excluded_countries']
        assert 'Italy' in call_kwargs['excluded_countries']

    def test_search_passes_excluded_airports(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&excl_airports=AGP,PMI&max_price=100')
        call_kwargs = mock.async_search_flights.call_args[1]
        assert 'AGP' in call_kwargs['excluded_airports']
        assert 'PMI' in call_kwargs['excluded_airports']

    def test_search_passes_flex_days(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&flex_days=3&max_price=100')
        call_kwargs = mock.async_search_flights.call_args[1]
        assert call_kwargs['flex_days'] == 3

    def test_search_passes_max_price(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=75')
        call_kwargs = mock.async_search_flights.call_args[1]
        assert call_kwargs['max_price'] == 75


class TestNomadAPI:
    """Тесты API endpoint /api/nomad/options."""

    def test_nomad_options_passes_dates_to_searcher(self, client):
        """Проверяем что API передаёт date_from/date_to в searcher без изменений."""
        c, mock = client
        mock.async_search_nomad_options = AsyncMock(return_value=[])

        c.get('/api/nomad/options?origin=VLC&date_from=2026-05-18&date_to=2026-05-18&max_leg_price=100&top_n=20')
        call_kwargs = mock.async_search_nomad_options.call_args[1]
        assert call_kwargs['date_from'] == '2026-05-18'
        assert call_kwargs['date_to'] == '2026-05-18'

    def test_nomad_options_two_nights_date_range(self, client):
        """arrival=May 19, nights=2 → frontend отправит date_from=date_to=May 21."""
        c, mock = client
        mock.async_search_nomad_options = AsyncMock(return_value=[
            {
                'destination': 'CTA', 'destination_name': 'Catania', 'country': 'Italy',
                'flight_number': 'FR 3736', 'price': 15.0, 'currency': 'EUR',
                'departure_time': '2026-05-21T10:00:00', 'arrival_time': '2026-05-21T11:00:00',
            }
        ])

        resp = c.get('/api/nomad/options?origin=PMO&date_from=2026-05-21&date_to=2026-05-21&max_leg_price=100&top_n=20')
        data = resp.json()
        assert resp.status_code == 200
        assert len(data['options']) == 1
        assert data['options'][0]['departure_time'][:10] == '2026-05-21'

    def test_nomad_options_missing_params(self, client):
        c, _ = client
        resp = c.get('/api/nomad/options?origin=VLC')
        assert resp.status_code == 400

    def test_nomad_options_exclusions(self, client):
        c, mock = client
        mock.async_search_nomad_options = AsyncMock(return_value=[])

        c.get('/api/nomad/options?origin=VLC&date_from=2026-05-18&date_to=2026-05-18&max_leg_price=100&top_n=20&excl_countries=Spain&excl_airports=AGP,PMI')
        call_kwargs = mock.async_search_nomad_options.call_args[1]
        assert 'Spain' in call_kwargs['excluded_countries']
        assert 'AGP' in call_kwargs['excluded_airports']
        assert 'PMI' in call_kwargs['excluded_airports']


class TestFreshnessIndicator:
    def test_fresh_indicator(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        resp = c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=100')
        assert resp.status_code == 200

    def test_stale_indicator_shown(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[Trip(
            total_price=45.0,
            outbound=Flight(
                origin='VLC', destination='TST', destination_name='Test',
                departure_time=datetime(2026, 5, 20, 10, 0),
                arrival_time=datetime(2026, 5, 20, 12, 0),
                flight_number='FR 1', price=20.0, currency='EUR',
            ),
            inbound=Flight(
                origin='TST', destination='VLC',
                departure_time=datetime(2026, 5, 21, 18, 0),
                arrival_time=datetime(2026, 5, 21, 20, 0),
                flight_number='FR 2', price=25.0, currency='EUR',
            ),
            nights=1, stay_duration_hours=30.0,
        )])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': True, 'age_minutes': 15}

        resp = c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=100')
        html = resp.text
        assert '15' in html
        assert 'stale' in html


# ── P2: API Endpoints ──────────────────────────────────

class TestNomadRoutesEndpoint:
    def test_nomad_routes_returns_json(self, client):
        c, mock = client
        mock.async_search_nomad_routes = AsyncMock(return_value=[])
        resp = c.get('/api/nomad/routes?origin=VLC&departure_date=2026-05-19&hops=1')
        assert resp.status_code == 200
        data = resp.json()
        assert 'routes' in data

    def test_nomad_routes_missing_params_400(self, client):
        c, _ = client
        resp = c.get('/api/nomad/routes')
        assert resp.status_code == 400

    def test_nomad_routes_passes_hops(self, client):
        c, mock = client
        mock.async_search_nomad_routes = AsyncMock(return_value=[])
        c.get('/api/nomad/routes?origin=VLC&departure_date=2026-05-19&hops=3')
        kwargs = mock.async_search_nomad_routes.call_args[1]
        assert kwargs['hops'] == 3

    def test_nomad_routes_default_nights(self, client):
        c, mock = client
        mock.async_search_nomad_routes = AsyncMock(return_value=[])
        c.get('/api/nomad/routes?origin=VLC&departure_date=2026-05-19')
        kwargs = mock.async_search_nomad_routes.call_args[1]
        assert kwargs['nights_per_city'] == [1, 2, 3]


class TestNomadReturnEndpoint:
    def test_nomad_return_returns_flights(self, client):
        c, mock = client
        mock.async_search_nomad_return = AsyncMock(return_value=[{'flight_number': 'FR 1', 'price': 20}])
        resp = c.get('/api/nomad/return?origin=PMO&destination=VLC&date_from=2026-05-23&date_to=2026-05-23&max_price=100')
        assert resp.status_code == 200
        data = resp.json()
        assert 'flights' in data

    def test_nomad_return_missing_params_400(self, client):
        c, _ = client
        resp = c.get('/api/nomad/return?origin=PMO')
        assert resp.status_code == 400


class TestWarmEndpoint:
    def test_warm_valid_origin_200(self, client):
        c, _ = client
        resp = c.post('/api/warm', json={'origin': 'VLC'})
        assert resp.status_code == 200

    def test_warm_invalid_origin_400(self, client):
        c, _ = client
        resp = c.post('/api/warm', json={'origin': 'X'})
        assert resp.status_code == 422  # Pydantic validation error (min_length=3)


class TestInputValidation:
    def test_empty_origin_handled(self, client):
        c, mock = client
        mock.async_search_nomad_routes = AsyncMock(return_value=[])
        resp = c.get('/api/nomad/routes?origin=&departure_date=2026-05-19')
        assert resp.status_code == 400

    def test_invalid_date_handled(self, client):
        c, mock = client
        mock.async_search_nomad_routes = AsyncMock(side_effect=ValueError("Invalid date"))
        resp = c.get('/api/nomad/routes?origin=VLC&departure_date=not-a-date')
        assert resp.status_code == 500


class TestDestinationOverride:
    def test_search_with_destination_override(self, client):
        c, mock = client
        mock.async_search_flights = AsyncMock(return_value=[])
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}
        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&destination=PMO')
        kwargs = mock.async_search_flights.call_args[1]
        assert kwargs['destination'] == 'PMO'


class TestHealthEndpoints:
    def test_health_returns_ok(self, client):
        c, _ = client
        resp = c.get('/health')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'ok'

    def test_ready_returns_status(self, client):
        c, mock = client
        mock.cache_stats.return_value = {'size': 10, 'volume_mb': 0.5}
        resp = c.get('/ready')
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'ready'
        assert data['airports'] == 2


# ── New coverage: /api/destinations, serialize_trip, warm_origin ──


class TestApiDestinations:
    def test_destinations_success(self, client):
        c, mock = client
        mock.async_get_available_destinations = AsyncMock(return_value={
            'BGY': Destination(price=15.0, name='Milan Bergamo', country='Italy'),
        })

        with patch('app._warmed_origins', set()):
            resp = c.get('/api/destinations?origin=vlc&date=2026-05-20')
        assert resp.status_code == 200
        data = resp.json()
        assert data['origin'] == 'VLC'
        assert len(data['destinations']) == 1
        assert data['destinations'][0]['code'] == 'BGY'
        assert data['destinations'][0]['min_price'] == 15.0

    def test_destinations_missing_params_400(self, client):
        c, _ = client
        resp = c.get('/api/destinations?origin=VLC')
        assert resp.status_code == 400

    def test_destinations_flex_days(self, client):
        c, mock = client
        mock.async_get_available_destinations = AsyncMock(return_value={})

        with patch('app._warmed_origins', set()):
            c.get('/api/destinations?origin=VLC&date=2026-05-20&flex=3')
        args = mock.async_get_available_destinations.call_args
        # date_from = 2026-05-17, date_to = 2026-05-23
        assert args[0][1] == '2026-05-17'  # date_from
        assert args[0][2] == '2026-05-23'  # date_to

    def test_destinations_error_500(self, client):
        c, mock = client
        mock.async_get_available_destinations = AsyncMock(side_effect=Exception('API down'))

        with patch('app._warmed_origins', {'VLC'}):
            resp = c.get('/api/destinations?origin=VLC&date=2026-05-20')
        assert resp.status_code == 500
        assert 'error' in resp.json()


class TestSerializeTrip:
    def _make_trip(self):
        return Trip(
            total_price=45.123,
            outbound=Flight(
                origin='VLC', destination='BGY', destination_name='Milan Bergamo',
                departure_time=datetime(2026, 5, 20, 10, 30),
                arrival_time=datetime(2026, 5, 20, 12, 45),
                flight_number='FR 123', price=20.0, currency='EUR',
            ),
            inbound=Flight(
                origin='BGY', destination='VLC',
                departure_time=datetime(2026, 5, 21, 18, 15),
                arrival_time=datetime(2026, 5, 21, 20, 30),
                flight_number='FR 456', price=25.0, currency='EUR',
            ),
            nights=1, stay_duration_hours=29.5,
        )

    def test_serialize_trip_keys(self):
        from app import serialize_trip
        result = serialize_trip(self._make_trip())
        expected_keys = {
            'destination', 'dest_code', 'total_price', 'currency', 'nights',
            'stay_hours', 'out_date', 'out_dep', 'out_arr', 'out_flight',
            'in_date', 'in_dep', 'in_arr', 'in_flight',
        }
        assert set(result.keys()) == expected_keys

    def test_serialize_trip_formatting(self):
        from app import serialize_trip
        result = serialize_trip(self._make_trip())
        assert result['out_date'] == '20.05.2026'
        assert result['out_dep'] == '10:30'
        assert result['out_arr'] == '12:45'
        assert result['in_dep'] == '18:15'
        assert result['total_price'] == 45.12
        assert result['destination'] == 'Milan Bergamo'


class TestWarmOrigin:
    def test_warm_first_call(self):
        from app import warm_origin
        mock_searcher = MagicMock()
        mock_searcher.async_get_available_destinations = AsyncMock()

        with patch('app._warmed_origins', set()):
            asyncio.run(warm_origin('TST', mock_searcher))
        assert mock_searcher.async_get_available_destinations.called

    def test_warm_second_call_skips(self):
        from app import warm_origin
        mock_searcher = MagicMock()
        mock_searcher.async_get_available_destinations = AsyncMock()

        with patch('app._warmed_origins', {'TST'}):
            asyncio.run(warm_origin('TST', mock_searcher))
        assert not mock_searcher.async_get_available_destinations.called

    def test_warm_exception_handled(self):
        from app import warm_origin
        mock_searcher = MagicMock()
        mock_searcher.async_get_available_destinations = AsyncMock(side_effect=Exception('fail'))

        with patch('app._warmed_origins', set()):
            asyncio.run(warm_origin('ERR', mock_searcher))
        # no exception raised


class TestBuildAirportData:
    def test_normal(self):
        from app import _build_airport_data
        airports = [
            Airport(code='VLC', name='Valencia', country='Spain', lat=39.49, lng=-0.47),
            Airport(code='BGY', name='Milan Bergamo', country='Italy', lat=45.67, lng=9.70),
        ]
        countries, c2a, coords = _build_airport_data(airports)
        assert countries == ['Italy', 'Spain']
        assert 'VLC' in c2a['Spain']
        assert 'BGY' in c2a['Italy']
        assert coords['VLC'] == {'lat': 39.49, 'lng': -0.47}

    def test_empty_list(self):
        from app import _build_airport_data
        countries, c2a, coords = _build_airport_data([])
        assert countries == []
        assert c2a == {}
        assert coords == {}

    def test_missing_country(self):
        from app import _build_airport_data
        airports = [Airport(code='XXX', name='Unknown', country='')]
        countries, c2a, coords = _build_airport_data(airports)
        assert '' not in countries
        assert 'XXX' in c2a['']

    def test_duplicate_countries(self):
        from app import _build_airport_data
        airports = [
            Airport(code='VLC', name='Valencia', country='Spain'),
            Airport(code='AGP', name='Malaga', country='Spain'),
        ]
        countries, c2a, coords = _build_airport_data(airports)
        assert countries == ['Spain']
        assert sorted(c2a['Spain']) == ['AGP', 'VLC']


class TestWarmCacheLoop:
    def test_initial_warm_called(self):
        from app import warm_cache_loop
        mock_searcher = MagicMock()
        mock_searcher.config = {'origin_airport': 'VLC'}
        mock_searcher.async_get_available_destinations = AsyncMock()

        async def _run():
            with patch('app._warmed_origins', set()), \
                 patch('asyncio.sleep', new_callable=AsyncMock, side_effect=asyncio.CancelledError):
                try:
                    await warm_cache_loop(mock_searcher)
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run())
        assert mock_searcher.async_get_available_destinations.called

    def test_exception_handled(self):
        from app import warm_cache_loop
        mock_searcher = MagicMock()
        mock_searcher.config = {'origin_airport': 'VLC'}
        mock_searcher.async_get_available_destinations = AsyncMock(side_effect=Exception('boom'))

        async def _run():
            with patch('app._warmed_origins', set()), \
                 patch('asyncio.sleep', new_callable=AsyncMock, side_effect=asyncio.CancelledError):
                try:
                    await warm_cache_loop(mock_searcher)
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run())  # no unhandled exception
