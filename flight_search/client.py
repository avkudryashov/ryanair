"""HTTP-клиент для Ryanair API: endpoints, запросы, парсинг ответов."""
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import asyncio
import random
import time

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from flight_search.cache import SWRCache, TTL_AIRPORTS, TTL_DESTINATIONS, TTL_FLIGHTS
from models import Airport, Destination, Flight

log = structlog.get_logger()


def _is_retryable(exc: BaseException) -> bool:
    """Check if an HTTP error is retryable (429, 5xx, timeouts)."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


_retry_policy = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


class RyanairClient:
    """HTTP-клиент к API Ryanair с SWR-кэшированием."""

    # API endpoints
    AVAILABILITY_API = "https://www.ryanair.com/api/booking/v4/availability"
    FARFND_API = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"
    AIRPORTS_API = "https://www.ryanair.com/api/views/locate/5/airports/en/active"

    # Максимум параллельных запросов к API (HTTP/2 мультиплексирует на одном соединении)
    MAX_CONCURRENCY = 25

    # Список User-Agent для ротации (обновлено 2025)
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
    ]

    MAX_FLEX_DAYS = 6  # Ryanair API ограничение

    def __init__(self, cache: SWRCache, config: dict):
        self.cache = cache
        self.config = config

        self._http_limits = httpx.Limits(
            max_connections=40,
            max_keepalive_connections=20,
            keepalive_expiry=120,
        )
        self._http_timeout = httpx.Timeout(30.0, connect=10.0)

        # Persistent async client (managed via open/close or _get_client)
        self._client: httpx.AsyncClient | None = None

        # Отслеживание свежести данных для UI
        self._last_api_call_ts = 0
        self._served_from_stale = False

    def reset_stale_flag(self):
        """Reset stale flag before a new search."""
        self._served_from_stale = False

    async def open(self):
        """Create persistent AsyncClient for long-lived usage (FastAPI)."""
        self._client = httpx.AsyncClient(
            http2=True, limits=self._http_limits, timeout=self._http_timeout
        )

    async def close(self):
        """Close persistent AsyncClient."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def get_client(self):
        """Yield persistent client if available, else create temporary one."""
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient(
                http2=True, limits=self._http_limits, timeout=self._http_timeout
            ) as client:
                yield client

    def _get_random_headers(self) -> dict:
        return {
            'User-Agent': random.choice(self.USER_AGENTS),
        }

    # ── Airports ──────────────────────────────────────────────

    def get_airports(self) -> list[Airport]:
        """Получает список всех активных аэропортов Ryanair (SWR: 24ч fresh / 7д stale)."""
        key = "airports:all_active"
        fresh_ttl, stale_ttl = TTL_AIRPORTS
        cached, is_stale = self.cache.get(key, fresh_ttl, stale_ttl)
        if cached is not None and not is_stale:
            return [Airport.model_validate(ap) if isinstance(ap, dict) else ap for ap in cached]

        try:
            response = httpx.get(self.AIRPORTS_API, headers=self._get_random_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            airports = []
            for ap in data:
                airports.append(Airport(
                    code=ap.get('code', ''),
                    name=ap.get('name', ''),
                    city=ap.get('city', {}).get('name', ''),
                    country=ap.get('country', {}).get('name', ''),
                    country_code=ap.get('country', {}).get('code', ''),
                    schengen=ap.get('country', {}).get('schengen', False),
                    lat=ap.get('coordinates', {}).get('latitude', 0),
                    lng=ap.get('coordinates', {}).get('longitude', 0),
                ))

            airports.sort(key=lambda x: x.name)
            self.cache.set(key, [ap.model_dump() for ap in airports], stale_ttl)
            self._last_api_call_ts = time.time()
            return airports

        except Exception as e:
            log.error("airports_fetch_failed", error=str(e))
            if cached is not None:
                return [Airport.model_validate(ap) if isinstance(ap, dict) else ap for ap in cached]
            return []

    # ── Async HTTP helpers ────────────────────────────────────

    async def fetch_destinations(self, client: httpx.AsyncClient, params: dict) -> dict[str, Destination]:
        """Получает направления из farfnd API (кэш 30м fresh / 6ч stale-fallback)."""
        key = self.cache.key("dest", params.get("departureAirportIataCode"),
                             params.get("outboundDepartureDateFrom"),
                             params.get("outboundDepartureDateTo"))
        fresh_ttl, stale_ttl = TTL_DESTINATIONS
        cached, is_stale = self.cache.get(key, fresh_ttl, stale_ttl)

        if cached is not None and not is_stale:
            log.debug("destinations_cache_hit", origin=params.get("departureAirportIataCode"))
            return {k: Destination.model_validate(v) if isinstance(v, dict) else v for k, v in cached.items()}

        try:
            return await self._refresh_destinations(client, params, key, stale_ttl)
        except Exception as e:
            if cached is not None:
                log.warning("destinations_stale_fallback", error=str(e))
                self._served_from_stale = True
                return {k: Destination.model_validate(v) if isinstance(v, dict) else v for k, v in cached.items()}
            raise

    @_retry_policy
    async def _refresh_destinations(self, client, params, key, stale_ttl) -> dict[str, Destination]:
        """Фактический запрос направлений к API и обновление кэша."""
        response = await client.get(self.FARFND_API, params=params,
                                    headers=self._get_random_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()

        destinations: dict[str, Destination] = {}
        excluded_countries = self.config.get('excluded_countries', [])

        for fare in data.get('fares', []):
            outbound = fare.get('outbound', {})
            arrival_airport = outbound.get('arrivalAirport', {})
            dest = arrival_airport.get('iataCode')
            dest_name = arrival_airport.get('name', dest)
            dest_country = arrival_airport.get('countryName', '')
            price = outbound.get('price', {}).get('value')
            if price is None:
                continue

            if dest_country in excluded_countries:
                continue

            if dest and (dest not in destinations or price < destinations[dest].price):
                destinations[dest] = Destination(price=price, name=dest_name, country=dest_country)

        self.cache.set(key, {k: v.model_dump() for k, v in destinations.items()}, stale_ttl)
        self._last_api_call_ts = time.time()
        return destinations

    async def fetch_flights(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore,
        origin: str, destination: str, dest_name: str,
        date_out: str, flex_days_out: int = 0
    ) -> list[Flight]:
        """Получает рейсы через Availability API (кэш 5м fresh / 1ч stale-fallback)."""
        key = self.cache.key("flights", origin, destination, date_out, flex_days_out)
        fresh_ttl, stale_ttl = TTL_FLIGHTS
        cached, is_stale = self.cache.get(key, fresh_ttl, stale_ttl)

        if cached is not None and not is_stale:
            return [Flight.model_validate(f) for f in cached]

        try:
            return await self._refresh_flights(client, sem, origin, destination, dest_name, date_out, flex_days_out, key, stale_ttl)
        except Exception as e:
            if cached is not None:
                self._served_from_stale = True
                return [Flight.model_validate(f) for f in cached]
            raise

    @_retry_policy
    async def _refresh_flights(self, client, sem, origin, destination, dest_name, date_out, flex_days_out, key, stale_ttl):
        """Фактический запрос рейсов к API и обновление кэша."""
        params = {
            "ADT": 1, "CHD": 0, "DateOut": date_out,
            "Destination": destination, "FlexDaysOut": flex_days_out,
            "INF": 0, "Origin": origin, "RoundTrip": "false",
            "TEEN": 0, "ToUs": "AGREED"
        }

        async with sem:
            response = await client.get(self.AVAILABILITY_API, params=params,
                                        headers=self._get_random_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

        flights = self._parse_flights(data, dest_name)

        self.cache.set(key, [f.model_dump(mode='json') for f in flights], stale_ttl)
        self._last_api_call_ts = time.time()
        return flights

    def _parse_flights(self, data: dict, fallback_dest_name: str = "") -> list[Flight]:
        """Парсит ответ Availability API в список рейсов."""
        flights = []
        for trip in data.get('trips', []):
            origin_name = trip.get('originName', '')
            dest_name = trip.get('destinationName', fallback_dest_name)

            for date_entry in trip.get('dates', []):
                for flight in date_entry.get('flights', []):
                    segments = flight.get('segments', [])
                    if not segments:
                        continue

                    segment = segments[0]
                    times = segment.get('time', [])
                    if len(times) < 2:
                        continue

                    regular_fare = flight.get('regularFare', {})
                    fares = regular_fare.get('fares', [])
                    if not fares:
                        continue

                    price = fares[0].get('amount', float('inf'))

                    flights.append(Flight(
                        origin=segment['origin'],
                        origin_name=origin_name,
                        destination=segment['destination'],
                        destination_name=dest_name,
                        departure_time=datetime.fromisoformat(times[0].replace('Z', '+00:00')),
                        arrival_time=datetime.fromisoformat(times[1].replace('Z', '+00:00')),
                        flight_number=segment['flightNumber'],
                        price=price,
                        currency=self.config['currency'],
                    ))
        return flights

    def build_date_batches(self, date_from: str, date_to: str) -> list[tuple]:
        """Разбивает диапазон дат на батчи по MAX_FLEX_DAYS."""
        dt_from = datetime.strptime(date_from, '%Y-%m-%d')
        dt_to = datetime.strptime(date_to, '%Y-%m-%d')
        total_days = (dt_to - dt_from).days

        if total_days <= self.MAX_FLEX_DAYS:
            return [(date_from, total_days)]

        batches = []
        current = dt_from
        while current < dt_to:
            remaining = (dt_to - current).days
            flex = min(remaining, self.MAX_FLEX_DAYS)
            batches.append((current.strftime('%Y-%m-%d'), flex))
            current += timedelta(days=flex + 1)
        return batches

    def get_data_freshness(self) -> dict:
        """Возвращает информацию о свежести данных для UI."""
        if self._last_api_call_ts == 0:
            return {'from_cache': True, 'stale': False, 'age_minutes': None}
        age_min = round((time.time() - self._last_api_call_ts) / 60)
        return {
            'from_cache': not self._served_from_stale and age_min > 0,
            'stale': self._served_from_stale,
            'age_minutes': age_min,
        }
