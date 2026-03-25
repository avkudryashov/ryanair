"""Pydantic models for domain objects and API request/response validation."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Domain models ──────────────────────────────────────────


class Airport(BaseModel):
    code: str
    name: str
    city: str = ""
    country: str = ""
    country_code: str = ""
    schengen: bool = False
    lat: float = 0.0
    lng: float = 0.0


class Destination(BaseModel):
    price: float
    name: str
    country: str = ""


class Flight(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    origin: str
    origin_name: str = Field("", alias="originName")
    destination: str
    destination_name: str = Field("", alias="destinationName")
    departure_time: datetime = Field(..., alias="departureTime")
    arrival_time: datetime = Field(..., alias="arrivalTime")
    flight_number: str = Field(..., alias="flightNumber")
    price: float
    currency: str
    # Nomad synthetic fields (populated during BFS, empty otherwise)
    dest_name: str = ""
    country_name: str = ""


class Trip(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_price: float = Field(..., alias="totalPrice")
    outbound: Flight
    inbound: Flight
    nights: int
    stay_duration_hours: float = 0.0
    destination_full: str = ""


class NomadLeg(BaseModel):
    flight: Flight
    dest: str
    dest_name: str
    country: str = ""
    arrival_date: str
    stay_nights: int = 0


class NomadRoute(BaseModel):
    legs: list[NomadLeg]
    return_flight: Flight
    total_price: float
    currency: str


# ── API request/response models ────────────────────────────


class WarmRequest(BaseModel):
    origin: str = Field(..., min_length=3, max_length=3)


class WarmResponse(BaseModel):
    status: str
    origin: str


class ErrorResponse(BaseModel):
    error: str


class DestinationInfo(BaseModel):
    code: str
    name: str
    country: str = ""
    min_price: float = 0


class DestinationsResponse(BaseModel):
    origin: str
    destinations: list[DestinationInfo]


class NomadOptionsResponse(BaseModel):
    origin: str
    options: list[dict]


class NomadRoutesResponse(BaseModel):
    origin: str
    routes: list[dict]


class NomadReturnResponse(BaseModel):
    flights: list[dict]
