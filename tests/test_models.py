"""Tests for Pydantic models validation and serialization."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from models import (
    WarmRequest, Flight, Trip, Airport, Destination,
    NomadLeg, NomadRoute, WarmResponse, ErrorResponse,
    DestinationInfo, DestinationsResponse,
    NomadOptionsResponse, NomadRoutesResponse, NomadReturnResponse,
)


class TestWarmRequest:
    def test_valid_3_char(self):
        req = WarmRequest(origin='VLC')
        assert req.origin == 'VLC'

    def test_too_short_raises(self):
        with pytest.raises(ValidationError):
            WarmRequest(origin='AB')

    def test_too_long_raises(self):
        with pytest.raises(ValidationError):
            WarmRequest(origin='ABCD')


def _sample_flight(**overrides):
    defaults = dict(
        origin='VLC', destination='BGY',
        departure_time=datetime(2026, 5, 20, 10, 0),
        arrival_time=datetime(2026, 5, 20, 12, 0),
        flight_number='FR 1', price=20.0, currency='EUR',
    )
    defaults.update(overrides)
    return Flight(**defaults)


class TestFlightModel:
    def test_validate_with_alias(self):
        f = Flight.model_validate({
            'origin': 'VLC', 'destination': 'BGY',
            'departureTime': '2026-05-20T10:00:00',
            'arrivalTime': '2026-05-20T12:00:00',
            'flightNumber': 'FR 1', 'price': 20.0, 'currency': 'EUR',
        })
        assert isinstance(f.departure_time, datetime)
        assert f.flight_number == 'FR 1'

    def test_validate_with_field_name(self):
        f = Flight.model_validate({
            'origin': 'VLC', 'destination': 'BGY',
            'departure_time': '2026-05-20T10:00:00',
            'arrival_time': '2026-05-20T12:00:00',
            'flight_number': 'FR 1', 'price': 20.0, 'currency': 'EUR',
        })
        assert f.flight_number == 'FR 1'


class TestTripSerialization:
    def test_round_trip_json(self):
        trip = Trip(
            total_price=45.0,
            outbound=_sample_flight(),
            inbound=_sample_flight(origin='BGY', destination='VLC',
                                    departure_time=datetime(2026, 5, 21, 18, 0),
                                    arrival_time=datetime(2026, 5, 21, 20, 0),
                                    flight_number='FR 2', price=25.0),
            nights=1, stay_duration_hours=30.0,
        )
        data = trip.model_dump(mode='json')
        restored = Trip.model_validate(data)
        assert restored.total_price == 45.0
        assert restored.nights == 1
        assert restored.outbound.flight_number == 'FR 1'


class TestAirportModel:
    def test_all_fields(self):
        ap = Airport(
            code='VLC', name='Valencia', city='Valencia',
            country='Spain', country_code='ES', schengen=True,
            lat=39.49, lng=-0.47,
        )
        assert ap.code == 'VLC'
        assert ap.country == 'Spain'
        assert ap.schengen is True
        assert ap.lat == 39.49

    def test_defaults(self):
        ap = Airport(code='VLC', name='Valencia')
        assert ap.city == ''
        assert ap.country == ''
        assert ap.country_code == ''
        assert ap.schengen is False
        assert ap.lat == 0.0
        assert ap.lng == 0.0


class TestDestinationModel:
    def test_create(self):
        d = Destination(price=15.0, name='Milan Bergamo', country='Italy')
        assert d.price == 15.0
        assert d.name == 'Milan Bergamo'
        assert d.country == 'Italy'

    def test_default_country(self):
        d = Destination(price=10.0, name='Test')
        assert d.country == ''


class TestNomadLegModel:
    def test_create(self):
        leg = NomadLeg(
            flight=_sample_flight(),
            dest='BGY', dest_name='Milan Bergamo',
            country='Italy', arrival_date='2026-05-20',
            stay_nights=2,
        )
        assert leg.dest == 'BGY'
        assert leg.stay_nights == 2
        assert leg.flight.price == 20.0

    def test_default_stay_nights(self):
        leg = NomadLeg(
            flight=_sample_flight(),
            dest='BGY', dest_name='Milan', arrival_date='2026-05-20',
        )
        assert leg.stay_nights == 0


class TestNomadRouteModel:
    def test_create(self):
        leg = NomadLeg(
            flight=_sample_flight(),
            dest='BGY', dest_name='Milan', arrival_date='2026-05-20',
            stay_nights=2,
        )
        ret = _sample_flight(origin='BGY', destination='VLC', flight_number='FR 2', price=25.0)
        route = NomadRoute(legs=[leg], return_flight=ret, total_price=45.0, currency='EUR')
        assert len(route.legs) == 1
        assert route.total_price == 45.0
        assert route.return_flight.flight_number == 'FR 2'


class TestResponseModels:
    def test_warm_response(self):
        r = WarmResponse(status='ok', origin='VLC')
        assert r.status == 'ok'

    def test_error_response(self):
        r = ErrorResponse(error='something failed')
        assert r.error == 'something failed'

    def test_destination_info(self):
        di = DestinationInfo(code='BGY', name='Milan', country='Italy', min_price=15.0)
        assert di.min_price == 15.0

    def test_destinations_response(self):
        di = DestinationInfo(code='BGY', name='Milan', min_price=10.0)
        dr = DestinationsResponse(origin='VLC', destinations=[di])
        assert dr.origin == 'VLC'
        assert len(dr.destinations) == 1

    def test_nomad_options_response(self):
        r = NomadOptionsResponse(origin='VLC', options=[])
        assert r.options == []

    def test_nomad_routes_response(self):
        r = NomadRoutesResponse(origin='VLC', routes=[])
        assert r.routes == []

    def test_nomad_return_response(self):
        r = NomadReturnResponse(flights=[])
        assert r.flights == []
