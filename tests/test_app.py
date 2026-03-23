"""Тесты Flask-приложения."""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from tests.conftest import AIRPORTS_RESPONSE


@pytest.fixture
def client():
    """Flask test client."""
    with patch('app.searcher') as mock_searcher:
        mock_searcher.get_airports.return_value = [
            {'code': 'VLC', 'name': 'Valencia', 'city': 'Valencia', 'country': 'Spain', 'country_code': 'es', 'schengen': True},
            {'code': 'BGY', 'name': 'Milan Bergamo', 'city': 'Bergamo', 'country': 'Italy', 'country_code': 'it', 'schengen': True},
        ]
        mock_searcher.config = {'max_price': 100, 'currency': 'EUR'}

        from app import app
        app.config['TESTING'] = True
        with app.test_client() as c:
            yield c, mock_searcher


class TestIndexPage:
    def test_index_returns_200(self, client):
        c, _ = client
        resp = c.get('/')
        assert resp.status_code == 200

    def test_index_contains_form(self, client):
        c, _ = client
        resp = c.get('/')
        html = resp.data.decode()
        assert 'search-form' in html
        assert 'departure_date' in html

    def test_index_contains_airports(self, client):
        c, _ = client
        resp = c.get('/')
        html = resp.data.decode()
        assert 'VLC' in html
        assert 'Valencia' in html


class TestSearchRegular:
    def test_search_returns_results(self, client):
        c, mock = client
        mock.search_flights.return_value = [{
            'totalPrice': 45.0,
            'outbound': {
                'destinationName': 'Milan Bergamo', 'destination': 'BGY',
                'departureTime': datetime(2026, 5, 20, 10, 0),
                'arrivalTime': datetime(2026, 5, 20, 12, 0),
                'flightNumber': 'FR 123', 'currency': 'EUR',
            },
            'inbound': {
                'departureTime': datetime(2026, 5, 21, 18, 0),
                'arrivalTime': datetime(2026, 5, 21, 20, 0),
                'flightNumber': 'FR 456',
            },
            'nights': 1,
            'stay_duration_hours': 30.0,
        }]
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        resp = c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=100')
        html = resp.data.decode()
        assert resp.status_code == 200
        assert '45.0' in html
        assert 'Milan Bergamo' in html

    def test_search_missing_date_shows_error(self, client):
        c, _ = client
        resp = c.get('/?mode=regular&nights=1')
        html = resp.data.decode()
        assert resp.status_code == 200
        assert 'Укажите дату' in html

    def test_search_passes_excluded_countries(self, client):
        c, mock = client
        mock.search_flights.return_value = []
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&excl_countries=Spain,Italy&max_price=100')
        call_kwargs = mock.search_flights.call_args[1]
        assert 'Spain' in call_kwargs['excluded_countries_override']
        assert 'Italy' in call_kwargs['excluded_countries_override']

    def test_search_passes_excluded_airports(self, client):
        c, mock = client
        mock.search_flights.return_value = []
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&excl_airports=AGP,PMI&max_price=100')
        call_kwargs = mock.search_flights.call_args[1]
        assert 'AGP' in call_kwargs['excluded_airports_override']
        assert 'PMI' in call_kwargs['excluded_airports_override']

    def test_search_passes_flex_days(self, client):
        c, mock = client
        mock.search_flights.return_value = []
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&flex_days=3&max_price=100')
        call_kwargs = mock.search_flights.call_args[1]
        assert call_kwargs['flex_days_override'] == 3

    def test_search_passes_max_price(self, client):
        c, mock = client
        mock.search_flights.return_value = []
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=75')
        call_kwargs = mock.search_flights.call_args[1]
        assert call_kwargs['max_price_override'] == 75


class TestFreshnessIndicator:
    def test_fresh_indicator(self, client):
        c, mock = client
        mock.search_flights.return_value = []
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': False, 'age_minutes': 0}

        resp = c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=100')
        # Нет результатов — нет индикатора (он в блоке results)
        assert resp.status_code == 200

    def test_stale_indicator_shown(self, client):
        c, mock = client
        mock.search_flights.return_value = [{
            'totalPrice': 45.0,
            'outbound': {
                'destinationName': 'Test', 'destination': 'TST',
                'departureTime': datetime(2026, 5, 20, 10, 0),
                'arrivalTime': datetime(2026, 5, 20, 12, 0),
                'flightNumber': 'FR 1', 'currency': 'EUR',
            },
            'inbound': {
                'departureTime': datetime(2026, 5, 21, 18, 0),
                'arrivalTime': datetime(2026, 5, 21, 20, 0),
                'flightNumber': 'FR 2',
            },
            'nights': 1, 'stay_duration_hours': 30.0,
        }]
        mock.get_data_freshness.return_value = {'from_cache': False, 'stale': True, 'age_minutes': 15}

        resp = c.get('/?mode=regular&departure_date=2026-05-20&nights=1&max_price=100')
        html = resp.data.decode()
        assert '15' in html
        assert 'stale' in html
