"""Tests for flight_search/utils.py — deduplication, filtering, exclusion sets."""
from datetime import datetime

from flight_search.utils import deduplicate_flights, filter_excluded, build_exclusion_sets
from models import Destination, Flight


def _make_flight(origin, dest, dep_str, flight_num, price=20.0):
    return Flight(
        origin=origin, destination=dest,
        departure_time=datetime.fromisoformat(dep_str),
        arrival_time=datetime.fromisoformat(dep_str),
        flight_number=flight_num, price=price, currency='EUR',
    )


class TestDeduplicateFlights:
    def test_empty_list(self):
        assert deduplicate_flights([]) == []

    def test_single_flight(self):
        f = _make_flight('VLC', 'BGY', '2026-05-20T10:00:00', 'FR 1')
        assert deduplicate_flights([f]) == [f]

    def test_duplicates_removed(self):
        f1 = _make_flight('VLC', 'BGY', '2026-05-20T10:00:00', 'FR 1', price=20)
        f2 = _make_flight('VLC', 'BGY', '2026-05-20T10:00:00', 'FR 1', price=30)
        result = deduplicate_flights([f1, f2])
        assert len(result) == 1
        assert result[0].price == 20  # first wins

    def test_custom_key_fields(self):
        f1 = _make_flight('VLC', 'BGY', '2026-05-20T10:00:00', 'FR 1')
        f2 = _make_flight('VLC', 'BGY', '2026-05-20T12:00:00', 'FR 2')
        result = deduplicate_flights([f1, f2], key_fields=('origin', 'destination'))
        assert len(result) == 1


class TestFilterExcluded:
    DESTS = {
        'BGY': Destination(price=15, name='Milan Bergamo', country='Italy'),
        'MXP': Destination(price=20, name='Milan Malpensa', country='Italy'),
        'STN': Destination(price=10, name='London Stansted', country='United Kingdom'),
        'AGP': Destination(price=12, name='Malaga', country='Spain'),
    }

    def test_no_exclusions(self):
        result = filter_excluded(self.DESTS)
        assert len(result) == 4

    def test_exclude_airports_only(self):
        result = filter_excluded(self.DESTS, excluded_airports={'BGY'})
        assert 'BGY' not in result
        assert len(result) == 3

    def test_exclude_countries_only(self):
        result = filter_excluded(self.DESTS, excluded_countries={'Italy'})
        assert 'BGY' not in result
        assert 'MXP' not in result
        assert len(result) == 2

    def test_exclude_both(self):
        result = filter_excluded(self.DESTS, excluded_airports={'AGP'}, excluded_countries={'Italy'})
        assert list(result.keys()) == ['STN']


class TestBuildExclusionSets:
    def test_empty_config(self):
        ap, co = build_exclusion_sets({})
        assert ap == set()
        assert co == set()

    def test_merge_config_and_override(self):
        config = {'excluded_airports': ['AGP'], 'excluded_countries': ['UK']}
        ap, co = build_exclusion_sets(config, excluded_airports=['PMI'], excluded_countries=['Ireland'])
        assert ap == {'AGP', 'PMI'}
        assert co == {'UK', 'Ireland'}

    def test_missing_keys_in_config(self):
        config = {'currency': 'EUR'}
        ap, co = build_exclusion_sets(config, excluded_airports=['BGY'])
        assert ap == {'BGY'}
        assert co == set()
