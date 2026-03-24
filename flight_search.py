"""
Модуль для поиска дешевых рейсов из Валенсии через прямые запросы к API Ryanair.
Использует httpx async для параллельных запросов и diskcache (SQLite) с stale-while-revalidate.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import yaml
import httpx
import asyncio
import random
import time
import diskcache
from cachetools import TTLCache


# TTL конфигурация (fresh_seconds, stale_seconds)
# fresh: данные считаются свежими, API не трогаем
# stale: данные устарели но пригодны — отдаём мгновенно + обновляем в фоне
TTL_AIRPORTS = (86400, 604800)       # 24ч fresh, 7 дней stale
TTL_DESTINATIONS = (1800, 21600)     # 30 мин fresh, 6ч stale
TTL_FLIGHTS = (300, 3600)            # 5 мин fresh, 1ч stale


class FlightSearcher:
    """Класс для поиска рейсов через асинхронные запросы к API Ryanair."""

    # API endpoints
    AVAILABILITY_API = "https://www.ryanair.com/api/booking/v4/availability"
    FARFND_API = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"
    AIRPORTS_API = "https://www.ryanair.com/api/views/locate/5/airports/en/active"

    # Максимум параллельных запросов к API (HTTP/2 мультиплексирует на одном соединении)
    MAX_CONCURRENCY = 25

    # Список User-Agent для ротации
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    ]

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        self.origin = self.config['origin_airport']

        # L2: Persistent SQLite кэш (переживает рестарт)
        self._cache = diskcache.Cache(".cache_data", size_limit=256 * 1024 * 1024)

        # L1: In-memory TTL cache (микросекунды vs SQLite миллисекунды)
        self._l1 = TTLCache(maxsize=4096, ttl=300)  # 5 мин, ~4K записей

        # httpx config для async clients (создаются per-request, но с оптимальными параметрами)
        self._http_limits = httpx.Limits(
            max_connections=40,
            max_keepalive_connections=20,
            keepalive_expiry=120,
        )
        self._http_timeout = httpx.Timeout(30.0, connect=10.0)

        # Отслеживание свежести данных для UI
        self._last_api_call_ts = 0  # timestamp последнего реального обращения к API
        self._served_from_stale = False

    def _get_random_headers(self) -> dict:
        return {
            'User-Agent': random.choice(self.USER_AGENTS),
        }

    def _cache_key(self, *parts) -> str:
        return "|".join(str(p) for p in parts)

    # ── SWR cache helpers ─────────────────────────────────────

    def _cache_get(self, key: str, fresh_ttl: int, stale_ttl: int) -> Tuple[any, bool]:
        """
        L1 (in-memory) → L2 (diskcache/SQLite) с Stale-While-Revalidate.
        Returns: (data, is_stale)
        """
        # L1: in-memory (только fresh данные)
        l1_val = self._l1.get(key)
        if l1_val is not None:
            return l1_val, False

        # L2: diskcache (SQLite)
        raw = self._cache.get(key)
        if raw is None:
            return None, False
        data, timestamp = raw
        age = time.time() - timestamp
        if age < fresh_ttl:
            self._l1[key] = data  # promote to L1
            return data, False  # свежие
        elif age < stale_ttl:
            return data, True   # stale — отдаём, но нужно обновить
        else:
            return None, False  # полностью протухли

    def _cache_set(self, key: str, data: any, stale_ttl: int):
        """Сохраняет в L1 + L2."""
        now = time.time()
        self._l1[key] = data  # L1
        self._cache.set(key, (data, now), expire=stale_ttl)  # L2

    def cache_stats(self) -> dict:
        """Статистика кэша для отладки."""
        return {
            'size': len(self._cache),
            'volume_mb': round(self._cache.volume() / 1024 / 1024, 1),
        }

    # ── Airports ──────────────────────────────────────────────

    def get_airports(self) -> List[Dict]:
        """Получает список всех активных аэропортов Ryanair (SWR: 24ч fresh / 7д stale)."""
        key = "airports:all_active"
        fresh_ttl, stale_ttl = TTL_AIRPORTS
        cached, is_stale = self._cache_get(key, fresh_ttl, stale_ttl)
        if cached is not None and not is_stale:
            return cached

        try:
            response = httpx.get(self.AIRPORTS_API, headers=self._get_random_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            airports = []
            for ap in data:
                airports.append({
                    'code': ap.get('code', ''),
                    'name': ap.get('name', ''),
                    'city': ap.get('city', {}).get('name', ''),
                    'country': ap.get('country', {}).get('name', ''),
                    'country_code': ap.get('country', {}).get('code', ''),
                    'schengen': ap.get('country', {}).get('schengen', False),
                    'lat': ap.get('coordinates', {}).get('latitude', 0),
                    'lng': ap.get('coordinates', {}).get('longitude', 0),
                })

            airports.sort(key=lambda x: x['name'])
            self._cache_set(key, airports, stale_ttl)
            self._last_api_call_ts = time.time()
            return airports

        except Exception as e:
            print(f"Ошибка при получении списка аэропортов: {e}")
            # При ошибке API — вернуть stale данные если есть
            if cached is not None:
                return cached
            return []

    # ── Async HTTP helpers ────────────────────────────────────

    async def _fetch_destinations(self, client: httpx.AsyncClient, params: dict) -> Dict[str, Dict]:
        """Получает направления из farfnd API (кэш 30м fresh / 6ч stale-fallback)."""
        key = self._cache_key("dest", params.get("departureAirportIataCode"),
                              params.get("outboundDepartureDateFrom"),
                              params.get("outboundDepartureDateTo"))
        fresh_ttl, stale_ttl = TTL_DESTINATIONS
        cached, is_stale = self._cache_get(key, fresh_ttl, stale_ttl)

        if cached is not None and not is_stale:
            print("  (направления из кэша, свежие)")
            return cached

        # Stale или пусто — запрашиваем API, stale как fallback при ошибке
        try:
            return await self._refresh_destinations(client, params, key, stale_ttl)
        except Exception as e:
            if cached is not None:
                print(f"  (API ошибка, используем stale: {e})")
                self._served_from_stale = True
                return cached
            raise

    async def _refresh_destinations(self, client, params, key, stale_ttl):
        """Фактический запрос направлений к API и обновление кэша."""
        response = await client.get(self.FARFND_API, params=params,
                                    headers=self._get_random_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()

        destinations = {}
        excluded_countries = self.config.get('excluded_countries', [])

        for fare in data.get('fares', []):
            outbound = fare.get('outbound', {})
            arrival_airport = outbound.get('arrivalAirport', {})
            dest = arrival_airport.get('iataCode')
            dest_name = arrival_airport.get('name', dest)
            dest_country = arrival_airport.get('countryName', '')
            price = outbound.get('price', {}).get('value', float('inf'))

            if dest_country in excluded_countries:
                continue

            if dest and (dest not in destinations or price < destinations[dest]['price']):
                destinations[dest] = {
                    'price': price,
                    'name': dest_name,
                    'country': dest_country
                }

        self._cache_set(key, destinations, stale_ttl)
        self._last_api_call_ts = time.time()
        return destinations

    async def _fetch_flights(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore,
        origin: str, destination: str, dest_name: str,
        date_out: str, flex_days_out: int = 0
    ) -> List[Dict]:
        """Получает рейсы через Availability API (кэш 5м fresh / 1ч stale-fallback)."""
        key = self._cache_key("flights", origin, destination, date_out, flex_days_out)
        fresh_ttl, stale_ttl = TTL_FLIGHTS
        cached, is_stale = self._cache_get(key, fresh_ttl, stale_ttl)

        if cached is not None and not is_stale:
            return self._restore_datetimes(cached)

        # Stale или пусто — запрашиваем API, stale как fallback при ошибке
        try:
            return await self._refresh_flights(client, sem, origin, destination, dest_name, date_out, flex_days_out, key, stale_ttl)
        except Exception as e:
            if cached is not None:
                self._served_from_stale = True
                return self._restore_datetimes(cached)
            raise

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

        self._cache_set(key, [self._flight_to_cacheable(f) for f in flights], stale_ttl)
        self._last_api_call_ts = time.time()
        return flights

    def _parse_flights(self, data: dict, fallback_dest_name: str = "") -> List[Dict]:
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

                    flights.append({
                        'origin': segment['origin'],
                        'originName': origin_name,
                        'destination': segment['destination'],
                        'destinationName': dest_name,
                        'departureTime': datetime.fromisoformat(times[0].replace('Z', '+00:00')),
                        'arrivalTime': datetime.fromisoformat(times[1].replace('Z', '+00:00')),
                        'flightNumber': segment['flightNumber'],
                        'price': price,
                        'currency': self.config['currency']
                    })
        return flights

    @staticmethod
    def _flight_to_cacheable(flight: dict) -> dict:
        """Конвертирует рейс в формат для кэша (datetime → str)."""
        f = dict(flight)
        f['departureTime'] = f['departureTime'].isoformat()
        f['arrivalTime'] = f['arrivalTime'].isoformat()
        return f

    @staticmethod
    def _restore_datetimes(flights: list) -> List[Dict]:
        """Восстанавливает datetime из кэшированных строк."""
        result = []
        for f in flights:
            f = dict(f)
            f['departureTime'] = datetime.fromisoformat(f['departureTime'])
            f['arrivalTime'] = datetime.fromisoformat(f['arrivalTime'])
            result.append(f)
        return result

    MAX_FLEX_DAYS = 6  # Ryanair API ограничение

    def _build_date_batches(self, date_from: str, date_to: str) -> List[tuple]:
        """
        Разбивает диапазон дат на батчи по MAX_FLEX_DAYS.
        Возвращает [(date_out, flex_days_out), ...].
        """
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

    # ── Main search (regular) ─────────────────────────────────

    def search_flights(
        self,
        departure_date: str,
        nights: List[int],
        excluded_airports_override: List[str] = None,
        excluded_countries_override: List[str] = None,
        origin_override: str = None,
        flex_days_override: int = None,
        max_price_override: int = None,
        destination_override: str = None,
    ) -> List[Dict]:
        """Синхронная обёртка для async поиска рейсов."""
        self._served_from_stale = False
        original_origin = self.origin
        if origin_override:
            self.origin = origin_override
        try:
            return asyncio.run(self._async_search_flights(
                departure_date, nights, excluded_airports_override,
                excluded_countries_override, flex_days_override, max_price_override,
                destination_override=destination_override,
            ))
        finally:
            self.origin = original_origin

    async def _async_search_flights(self, departure_date, nights, excluded_airports_override,
                                     excluded_countries_override=None, flex_days_override=None,
                                     max_price_override=None, destination_override=None):
        all_results = []

        excluded_airports = set(self.config.get('excluded_airports', []))
        if excluded_airports_override:
            excluded_airports.update(excluded_airports_override)

        date_flexibility = flex_days_override if flex_days_override is not None else self.config.get('date_flexibility_days', 0)
        departure_dt = datetime.strptime(departure_date, '%Y-%m-%d')

        outbound_date_from = (departure_dt - timedelta(days=date_flexibility)).strftime('%Y-%m-%d')
        outbound_date_to = (departure_dt + timedelta(days=date_flexibility)).strftime('%Y-%m-%d')

        max_nights = max(nights)
        min_nights = min(nights)
        # Возврат: самый ранний = самый ранний вылет + мин.ночей, самый поздний = самый поздний вылет + макс.ночей + 1
        return_date_from = (departure_dt - timedelta(days=date_flexibility) + timedelta(days=min_nights)).strftime('%Y-%m-%d')
        return_date_to = (departure_dt + timedelta(days=date_flexibility + max_nights + 1)).strftime('%Y-%m-%d')

        print(f"Параметры: дата={departure_date}, ±{date_flexibility} дн, ночей={nights}")
        print(f"  Вылет: {outbound_date_from}..{outbound_date_to} (FlexDaysOut={date_flexibility * 2})")
        print(f"  Возврат: {return_date_from}..{return_date_to}")

        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async with httpx.AsyncClient(http2=True, limits=self._http_limits, timeout=self._http_timeout) as client:
            # Шаг 1: направления
            print(f"\nПолучение направлений из {self.origin}...")
            dest_params = {
                "departureAirportIataCode": self.origin,
                "outboundDepartureDateFrom": outbound_date_from,
                "outboundDepartureDateTo": outbound_date_to,
                "currency": self.config['currency']
            }
            destinations = await self._fetch_destinations(client, dest_params)

            if excluded_airports:
                destinations = {c: i for c, i in destinations.items() if c not in excluded_airports}

            # Фильтрация по странам (config + override)
            excluded_countries = set(self.config.get('excluded_countries', []))
            if excluded_countries_override:
                excluded_countries.update(excluded_countries_override)
            if excluded_countries:
                destinations = {c: i for c, i in destinations.items()
                                if i.get('country', '') not in excluded_countries}

            # Фильтрация по конкретному направлению
            if destination_override:
                dest_upper = destination_override.upper()
                destinations = {c: i for c, i in destinations.items() if c == dest_upper}

            print(f"Найдено {len(destinations)} направлений")
            if not destinations:
                return []

            # Шаг 2: все рейсы ТУДА — параллельно (батчами если диапазон > 6 дней)
            out_batches = self._build_date_batches(outbound_date_from, outbound_date_to)
            print(f"Получение рейсов туда ({len(destinations)} направлений x {len(out_batches)} батч(ей))...")

            outbound_task_list = []
            for dest, info in destinations.items():
                for batch_date, batch_flex in out_batches:
                    outbound_task_list.append((
                        dest,
                        self._fetch_flights(client, sem, self.origin, dest, info['name'], batch_date, flex_days_out=batch_flex)
                    ))

            outbound_results = await asyncio.gather(
                *[t[1] for t in outbound_task_list], return_exceptions=True
            )
            outbound_flights_by_dest = {}
            for (dest, _), result in zip(outbound_task_list, outbound_results):
                if isinstance(result, Exception):
                    if not (isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 400):
                        print(f"  Ошибка {dest}: {result}")
                elif result:
                    outbound_flights_by_dest.setdefault(dest, []).extend(result)

            # Дедупликация
            for dest in outbound_flights_by_dest:
                seen = set()
                unique = []
                for f in outbound_flights_by_dest[dest]:
                    key = (f['flightNumber'], f['departureTime'])
                    if key not in seen:
                        seen.add(key)
                        unique.append(f)
                outbound_flights_by_dest[dest] = unique

            total_out = sum(len(f) for f in outbound_flights_by_dest.values())
            print(f"Всего рейсов туда: {total_out}")

            # Шаг 3: все обратные рейсы — параллельно (батчами)
            ret_batches = self._build_date_batches(return_date_from, return_date_to)
            print(f"Получение обратных рейсов ({len(outbound_flights_by_dest)} направлений x {len(ret_batches)} батч(ей))...")
            print(f"  Возврат: {return_date_from}..{return_date_to}")

            inbound_task_list = []
            for dest in outbound_flights_by_dest:
                dest_name = destinations.get(dest, {}).get('name', dest)
                for batch_date, batch_flex in ret_batches:
                    inbound_task_list.append((
                        dest,
                        self._fetch_flights(client, sem, dest, self.origin, dest_name, batch_date, flex_days_out=batch_flex)
                    ))

            inbound_results = await asyncio.gather(
                *[t[1] for t in inbound_task_list], return_exceptions=True
            )
            inbound_flights_by_dest = {}
            for (dest, _), result in zip(inbound_task_list, inbound_results):
                if isinstance(result, Exception):
                    if not (isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 400):
                        print(f"  Ошибка обратно {dest}: {result}")
                elif result:
                    inbound_flights_by_dest.setdefault(dest, []).extend(result)

            # Дедупликация обратных
            for dest in inbound_flights_by_dest:
                seen = set()
                unique = []
                for f in inbound_flights_by_dest[dest]:
                    key = (f['flightNumber'], f['departureTime'])
                    if key not in seen:
                        seen.add(key)
                        unique.append(f)
                inbound_flights_by_dest[dest] = unique

            total_in = sum(len(f) for f in inbound_flights_by_dest.values())
            print(f"Всего обратных рейсов: {total_in}")

        # Шаг 4: комбинируем
        effective_max_price = max_price_override if max_price_override is not None else self.config['max_price']
        for night_count in nights:
            filtered_trips = self._combine_flights(
                outbound_flights_by_dest, inbound_flights_by_dest, night_count,
                max_price=effective_max_price
            )
            filtered_trips.sort(key=lambda x: x['totalPrice'])
            max_results = self.config['max_results']
            limited = filtered_trips[:max_results]
            all_results.extend(limited)
            self.print_results(limited, night_count)

        return all_results

    def _combine_flights(self, outbound_by_dest, inbound_by_dest, night_count, max_price=None):
        """Комбинирует рейсы туда/обратно и фильтрует по критериям."""
        filtered = []
        total = 0
        rejected_late = 0
        rejected_dur = 0
        rejected_min_h = 0
        rejected_price = 0

        max_arrival_time = datetime.strptime(
            self.config['max_arrival_time_destination'], "%H:%M"
        ).time()

        for dest, outbound_list in outbound_by_dest.items():
            inbound_list = inbound_by_dest.get(dest, [])
            if not inbound_list:
                continue

            for outbound in outbound_list:
                arrival_hour = outbound['arrivalTime'].time().replace(second=0, microsecond=0)
                if arrival_hour > max_arrival_time:
                    rejected_late += len(inbound_list)
                    total += len(inbound_list)
                    continue

                for inbound in inbound_list:
                    total += 1
                    stay_duration = (inbound['departureTime'] - outbound['arrivalTime']).total_seconds() / 3600

                    if night_count == 1:
                        min_hours = self.config['min_hours_for_one_night']
                        if stay_duration < min_hours:
                            rejected_min_h += 1
                            continue

                    # Считаем ночи по календарным датам (прилёт туда → вылет обратно)
                    calendar_nights = (inbound['departureTime'].date() - outbound['arrivalTime'].date()).days
                    if calendar_nights != night_count:
                        rejected_dur += 1
                        continue

                    total_price = outbound['price'] + inbound['price']
                    effective_price = max_price if max_price is not None else self.config['max_price']
                    if total_price > effective_price:
                        rejected_price += 1
                        continue

                    filtered.append({
                        'totalPrice': total_price,
                        'outbound': outbound,
                        'inbound': inbound,
                        'nights': night_count,
                        'stay_duration_hours': round(stay_duration, 1),
                        'destination_full': dest
                    })

        print(f"\n{'='*60}")
        print(f"{night_count} ноч.: проверено {total}, поздний прилёт -{rejected_late}, "
              f"длительность -{rejected_dur}, мин.часы -{rejected_min_h}, цена -{rejected_price} → {len(filtered)}")
        return filtered

    # ── One-day trips ─────────────────────────────────────────

    def search_one_day_trips(
        self,
        excluded_airports_override: List[str] = None,
        excluded_countries_override: List[str] = None,
        origin_override: str = None,
        max_price_override: int = None
    ) -> List[Dict]:
        """Синхронная обёртка для async поиска однодневных поездок."""
        self._served_from_stale = False
        original_origin = self.origin
        if origin_override:
            self.origin = origin_override
        try:
            return asyncio.run(self._async_search_one_day_trips(
                excluded_airports_override, excluded_countries_override, max_price_override
            ))
        finally:
            self.origin = original_origin

    async def _async_search_one_day_trips(self, excluded_airports_override, excluded_countries_override=None, max_price_override=None):
        all_results = []

        excluded_airports = set(self.config.get('excluded_airports', []))
        if excluded_airports_override:
            excluded_airports.update(excluded_airports_override)

        today = datetime.now().date()
        start_date = today + timedelta(days=1)
        end_date = today + timedelta(days=60)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        print(f"\nПоиск с {start_date_str} по {end_date_str}")

        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async with httpx.AsyncClient(http2=True, limits=self._http_limits, timeout=self._http_timeout) as client:
            # Шаг 1: направления
            print(f"Получение направлений из {self.origin}...")
            dest_params = {
                "departureAirportIataCode": self.origin,
                "outboundDepartureDateFrom": start_date_str,
                "outboundDepartureDateTo": end_date_str,
                "currency": self.config['currency']
            }
            destinations = await self._fetch_destinations(client, dest_params)

            if excluded_airports:
                destinations = {c: i for c, i in destinations.items() if c not in excluded_airports}

            # Фильтрация по странам
            excluded_countries = set(self.config.get('excluded_countries', []))
            if excluded_countries_override:
                excluded_countries.update(excluded_countries_override)
            if excluded_countries:
                destinations = {c: i for c, i in destinations.items()
                                if i.get('country', '') not in excluded_countries}

            print(f"Найдено {len(destinations)} направлений")
            if not destinations:
                return []

            # Шаг 2: для каждого направления — запрашиваем рейсы батчами по неделям
            # вместо 60 отдельных запросов используем FlexDaysOut=6 с шагом в неделю
            # ~9 запросов на направление вместо 60
            print(f"Получение рейсов по направлениям (батчами по неделям)...")

            # Генерируем «центральные» даты батчей
            batch_centers = []
            current = start_date + timedelta(days=3)  # центр первой недели
            while current <= end_date:
                batch_centers.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=7)

            # Собираем все задачи: outbound + return рейсы для каждого направления и батча
            outbound_tasks = []
            for dest, info in destinations.items():
                for center_date in batch_centers:
                    outbound_tasks.append((
                        dest, info['name'], center_date,
                        self._fetch_flights(client, sem, self.origin, dest, info['name'], center_date, flex_days_out=6)
                    ))

            print(f"  Запросов туда: {len(outbound_tasks)} (параллельно, semaphore={self.MAX_CONCURRENCY})")

            # Выполняем все outbound параллельно
            outbound_results = await asyncio.gather(
                *[t[3] for t in outbound_tasks], return_exceptions=True
            )

            # Собираем утренние рейсы по направлениям
            morning_flights_by_dest = {}
            for (dest, name, center, _), result in zip(outbound_tasks, outbound_results):
                if isinstance(result, Exception):
                    continue
                for f in result:
                    if f['departureTime'].time().hour < 12:
                        morning_flights_by_dest.setdefault(dest, []).append(f)

            # Дедупликация по flightNumber+date
            for dest in morning_flights_by_dest:
                seen = set()
                unique = []
                for f in morning_flights_by_dest[dest]:
                    key = (f['flightNumber'], f['departureTime'].date())
                    if key not in seen:
                        seen.add(key)
                        unique.append(f)
                morning_flights_by_dest[dest] = unique

            total_morning = sum(len(v) for v in morning_flights_by_dest.values())
            print(f"  Найдено {total_morning} утренних рейсов по {len(morning_flights_by_dest)} направлениям")

            # Шаг 3: обратные рейсы — тоже батчами
            return_tasks = []
            for dest in morning_flights_by_dest:
                dest_name = destinations.get(dest, {}).get('name', dest)
                for center_date in batch_centers:
                    return_tasks.append((
                        dest, center_date,
                        self._fetch_flights(client, sem, dest, self.origin, dest_name, center_date, flex_days_out=6)
                    ))

            print(f"  Запросов обратно: {len(return_tasks)} (параллельно)")

            return_results = await asyncio.gather(
                *[t[2] for t in return_tasks], return_exceptions=True
            )

            # Собираем вечерние обратные рейсы по направлениям
            evening_returns_by_dest = {}
            for (dest, center, _), result in zip(return_tasks, return_results):
                if isinstance(result, Exception):
                    continue
                for f in result:
                    if f['arrivalTime'].time().hour >= 18:
                        evening_returns_by_dest.setdefault(dest, []).append(f)

            # Дедупликация
            for dest in evening_returns_by_dest:
                seen = set()
                unique = []
                for f in evening_returns_by_dest[dest]:
                    key = (f['flightNumber'], f['departureTime'].date())
                    if key not in seen:
                        seen.add(key)
                        unique.append(f)
                evening_returns_by_dest[dest] = unique

            total_evening = sum(len(v) for v in evening_returns_by_dest.values())
            print(f"  Найдено {total_evening} вечерних обратных рейсов")

        # Шаг 4: комбинируем
        for dest, outbound_list in morning_flights_by_dest.items():
            inbound_list = evening_returns_by_dest.get(dest, [])
            if not inbound_list:
                continue

            for outbound in outbound_list:
                for inbound in inbound_list:
                    # Только с ночёвкой
                    if outbound['departureTime'].date() == inbound['arrivalTime'].date():
                        continue

                    stay_duration = (inbound['departureTime'] - outbound['arrivalTime']).total_seconds() / 3600
                    if stay_duration < 6 or stay_duration > 36:
                        continue

                    total_price = outbound['price'] + inbound['price']
                    effective_price = max_price_override if max_price_override is not None else self.config['max_price']
                    if total_price > effective_price:
                        continue

                    all_results.append({
                        'totalPrice': total_price,
                        'outbound': outbound,
                        'inbound': inbound,
                        'nights': 1,
                        'stay_duration_hours': round(stay_duration, 1),
                        'destination_full': dest
                    })

        all_results.sort(key=lambda x: x['totalPrice'])
        max_results = self.config['max_results']
        limited = all_results[:max_results]
        self.print_one_day_results(limited)
        return limited

    # ── Sync wrappers for backward compatibility ──────────────

    def get_available_destinations(self, date_from: str, date_to: str) -> Dict[str, Dict]:
        """Синхронная обёртка для CLI (с SWR)."""
        key = self._cache_key("dest", self.origin, date_from, date_to)
        fresh_ttl, stale_ttl = TTL_DESTINATIONS
        cached, is_stale = self._cache_get(key, fresh_ttl, stale_ttl)
        if cached is not None and not is_stale:
            return cached

        params = {
            "departureAirportIataCode": self.origin,
            "outboundDepartureDateFrom": date_from,
            "outboundDepartureDateTo": date_to,
            "currency": self.config['currency']
        }

        try:
            response = httpx.get(self.FARFND_API, params=params,
                                 headers=self._get_random_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            destinations = {}
            excluded_countries = self.config.get('excluded_countries', [])

            for fare in data.get('fares', []):
                outbound = fare.get('outbound', {})
                arrival_airport = outbound.get('arrivalAirport', {})
                dest = arrival_airport.get('iataCode')
                dest_name = arrival_airport.get('name', dest)
                dest_country = arrival_airport.get('countryName', '')
                price = outbound.get('price', {}).get('value', float('inf'))

                if dest_country in excluded_countries:
                    continue

                if dest and (dest not in destinations or price < destinations[dest]['price']):
                    destinations[dest] = {
                        'price': price,
                        'name': dest_name,
                        'country': dest_country
                    }

            self._cache_set(key, destinations, stale_ttl)
            self._last_api_call_ts = time.time()
            return destinations

        except Exception as e:
            print(f"Ошибка при получении направлений: {e}")
            if cached is not None:
                return cached
            return {}

    # ── Nomad mode ─────────────────────────────────────────────

    def search_nomad_options(
        self,
        origin: str,
        date_from: str,
        date_to: str,
        max_price_per_leg: int = 50,
        top_n: int = 10,
        excluded_airports: List[str] = None,
        excluded_countries: List[str] = None,
    ) -> List[Dict]:
        """Возвращает top-N дешёвых one-way рейсов из указанного аэропорта."""
        self._served_from_stale = False
        return asyncio.run(self._async_search_nomad_options(
            origin, date_from, date_to, max_price_per_leg, top_n,
            excluded_airports, excluded_countries,
        ))

    async def _async_search_nomad_options(
        self, origin, date_from, date_to, max_price_per_leg, top_n,
        excluded_airports, excluded_countries,
    ) -> List[Dict]:
        excluded_ap = set(self.config.get('excluded_airports', []))
        if excluded_airports:
            excluded_ap.update(excluded_airports)

        excluded_co = set(self.config.get('excluded_countries', []))
        if excluded_countries:
            excluded_co.update(excluded_countries)

        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async with httpx.AsyncClient(http2=True, limits=self._http_limits, timeout=self._http_timeout) as client:
            # Шаг 1: направления
            dest_params = {
                "departureAirportIataCode": origin,
                "outboundDepartureDateFrom": date_from,
                "outboundDepartureDateTo": date_to,
                "currency": self.config['currency'],
            }
            destinations = await self._fetch_destinations(client, dest_params)

            # Фильтрация
            if excluded_ap:
                destinations = {c: i for c, i in destinations.items() if c not in excluded_ap}
            if excluded_co:
                destinations = {c: i for c, i in destinations.items()
                                if i.get('country', '') not in excluded_co}

            if not destinations:
                return []

            # Шаг 2: рейсы параллельно (батчами)
            batches = self._build_date_batches(date_from, date_to)
            task_list = []
            for dest, info in destinations.items():
                for batch_date, batch_flex in batches:
                    task_list.append((
                        dest, info['name'], info.get('country', ''),
                        self._fetch_flights(client, sem, origin, dest, info['name'],
                                            batch_date, flex_days_out=batch_flex)
                    ))

            results = await asyncio.gather(
                *[t[3] for t in task_list], return_exceptions=True
            )

            # Собираем все рейсы, фильтруем по дате и цене
            dt_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            all_flights = []
            dest_info = {}
            for (dest, name, country, _), result in zip(task_list, results):
                dest_info[dest] = {'name': name, 'country': country}
                if isinstance(result, Exception):
                    continue
                for f in result:
                    dep_date = f['departureTime'].date()
                    if dep_date < dt_from or dep_date > dt_to:
                        continue
                    if f['price'] <= max_price_per_leg:
                        all_flights.append(f)

            # Дедупликация
            seen = set()
            unique = []
            for f in all_flights:
                key = (f['flightNumber'], f['departureTime'])
                if key not in seen:
                    seen.add(key)
                    unique.append(f)

            # Сортируем по цене, берём top_n
            unique.sort(key=lambda x: x['price'])
            top = unique[:top_n]

            # Сериализуем для JSON
            serialized = []
            for f in top:
                serialized.append({
                    'destination': f['destination'],
                    'destination_name': f.get('destinationName', f['destination']),
                    'country': dest_info.get(f['destination'], {}).get('country', ''),
                    'flight_number': f['flightNumber'],
                    'departure_time': f['departureTime'].isoformat(),
                    'arrival_time': f['arrivalTime'].isoformat(),
                    'price': f['price'],
                    'currency': f['currency'],
                })
            return serialized

    def search_nomad_return(
        self,
        origin: str,
        destination: str,
        date_from: str,
        date_to: str,
        max_price: int = 50,
    ) -> List[Dict]:
        """Ищет обратные рейсы origin → destination в диапазоне дат."""
        self._served_from_stale = False
        return asyncio.run(self._async_search_nomad_return(
            origin, destination, date_from, date_to, max_price,
        ))

    async def _async_search_nomad_return(
        self, origin, destination, date_from, date_to, max_price,
    ) -> List[Dict]:
        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async with httpx.AsyncClient(http2=True, limits=self._http_limits, timeout=self._http_timeout) as client:
            batches = self._build_date_batches(date_from, date_to)

            task_list = []
            for batch_date, batch_flex in batches:
                task_list.append(
                    self._fetch_flights(client, sem, origin, destination, '',
                                        batch_date, flex_days_out=batch_flex)
                )

            results = await asyncio.gather(*task_list, return_exceptions=True)

            dt_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            all_flights = []
            for result in results:
                if isinstance(result, Exception):
                    continue
                for f in result:
                    dep_date = f['departureTime'].date()
                    if dep_date < dt_from or dep_date > dt_to:
                        continue
                    if f['price'] <= max_price:
                        all_flights.append(f)

            # Дедупликация
            seen = set()
            unique = []
            for f in all_flights:
                key = (f['flightNumber'], f['departureTime'])
                if key not in seen:
                    seen.add(key)
                    unique.append(f)

            unique.sort(key=lambda x: (x['price'], x['departureTime']))

            serialized = []
            for f in unique:
                serialized.append({
                    'destination': f['destination'],
                    'destination_name': f.get('destinationName', f['destination']),
                    'flight_number': f['flightNumber'],
                    'departure_time': f['departureTime'].isoformat(),
                    'arrival_time': f['arrivalTime'].isoformat(),
                    'price': f['price'],
                    'currency': f['currency'],
                })
            return serialized

    # ── Nomad auto-routes ───────────────────────────────────────

    def search_nomad_routes(
        self,
        origin: str,
        departure_date: str,
        hops: int = 2,
        nights_per_city: List[int] = None,
        max_price_per_leg: int = 50,
        top_n: int = 10,
        excluded_airports: List[str] = None,
        excluded_countries: List[str] = None,
    ) -> List[Dict]:
        """Автоматический поиск nomad-маршрутов с возвратом в origin.

        Строит маршруты: origin → city1 → city2 → ... → origin
        Количество промежуточных городов = hops.
        Возврат в origin всегда включён.
        """
        self._served_from_stale = False
        if nights_per_city is None:
            nights_per_city = [1, 2, 3]
        hops = max(1, min(hops, 4))  # clamp 1-4
        return asyncio.run(self._async_search_nomad_routes(
            origin, departure_date, hops, nights_per_city,
            max_price_per_leg, top_n,
            excluded_airports, excluded_countries,
        ))

    async def _async_search_nomad_routes(
        self, origin, departure_date, hops, nights_per_city,
        max_price_per_leg, top_n, excluded_airports, excluded_countries,
    ) -> List[Dict]:
        min_nights = min(nights_per_city)
        max_nights = max(nights_per_city)

        excluded_ap = set(self.config.get('excluded_airports', []))
        if excluded_airports:
            excluded_ap.update(excluded_airports)
        excluded_co = set(self.config.get('excluded_countries', []))
        if excluded_countries:
            excluded_co.update(excluded_countries)

        sem = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async with httpx.AsyncClient(http2=True, limits=self._http_limits, timeout=self._http_timeout) as client:

            # ══════════════════════════════════════════════════════
            # ФАЗА 0: Вычисляем returnable_set — аэропорты, из
            # которых можно вернуться в origin.
            #
            # Ryanair маршруты бидирекциональны: если origin летает
            # в X, то X летает обратно в origin. Поэтому
            # _fetch_destinations(origin) даёт нам returnable_set.
            #
            # Оцениваем окно дат возврата для широкого диапазона,
            # чтобы не пропустить варианты.
            # ══════════════════════════════════════════════════════

            departure_dt = datetime.strptime(departure_date, '%Y-%m-%d')
            earliest_return = (departure_dt + timedelta(days=hops * min_nights)).strftime('%Y-%m-%d')
            latest_return = (departure_dt + timedelta(days=hops * max_nights + max_nights)).strftime('%Y-%m-%d')

            ret_dest_params = {
                "departureAirportIataCode": origin,
                "outboundDepartureDateFrom": earliest_return,
                "outboundDepartureDateTo": latest_return,
                "currency": self.config['currency'],
            }
            returnable_dests = await self._fetch_destinations(client, ret_dest_params)
            returnable_set = set(returnable_dests.keys())
            # Убираем excluded
            returnable_set -= excluded_ap
            if excluded_co:
                returnable_set = {c for c in returnable_set
                                  if returnable_dests.get(c, {}).get('country', '') not in excluded_co}

            print(f"[nomad] Returnable airports from {origin}: {len(returnable_set)}")
            if not returnable_set:
                print(f"[nomad] No returnable airports found, aborting")
                return []

            # ══════════════════════════════════════════════════════
            # Кэш рейсов + helper
            # ══════════════════════════════════════════════════════

            flights_cache = {}

            async def get_flights_from(airport, date_from, date_to, visited, only_dests=None):
                """Получает рейсы из аэропорта.
                only_dests: если задан, фильтруем destinations ПЕРЕД fetch_flights
                (экономит API-вызовы на последнем хопе).
                Кэш по (airport, date_from, date_to) — без only_dests чтобы
                переиспользовать между хопами. only_dests фильтрует destinations
                до вызова _fetch_flights (экономит API), но не ломает кэш.
                """
                # Для кэша: без only_dests, чтобы повторные запросы к тому же
                # аэропорту (с/без фильтра) переиспользовали данные.
                # Но если only_dests задан — кэш с полным набором не подходит,
                # нужен отдельный ключ чтобы не засорять его подмножеством.
                cache_key = (airport, date_from, date_to)
                use_full_cache = only_dests is None and cache_key in flights_cache

                if use_full_cache:
                    return [f for f in flights_cache[cache_key]
                            if f['destination'] not in visited]

                # Если уже есть полный кэш — фильтруем из него
                if only_dests is not None and cache_key in flights_cache:
                    return [f for f in flights_cache[cache_key]
                            if f['destination'] not in visited and f['destination'] in only_dests]

                dest_params = {
                    "departureAirportIataCode": airport,
                    "outboundDepartureDateFrom": date_from,
                    "outboundDepartureDateTo": date_to,
                    "currency": self.config['currency'],
                }
                destinations = await self._fetch_destinations(client, dest_params)
                if excluded_ap:
                    destinations = {c: i for c, i in destinations.items() if c not in excluded_ap}
                if excluded_co:
                    destinations = {c: i for c, i in destinations.items()
                                    if i.get('country', '') not in excluded_co}
                # Фильтр на последний хоп: только returnable аэропорты
                if only_dests is not None:
                    destinations = {c: i for c, i in destinations.items() if c in only_dests}

                batches = self._build_date_batches(date_from, date_to)
                task_list = []
                for dest, info in destinations.items():
                    for batch_date, batch_flex in batches:
                        task_list.append((
                            dest, info['name'], info.get('country', ''),
                            self._fetch_flights(client, sem, airport, dest, info['name'],
                                                batch_date, flex_days_out=batch_flex)
                        ))

                results = await asyncio.gather(*[t[3] for t in task_list], return_exceptions=True)

                dt_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                dt_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                all_flights = []
                for (dest, name, country, _), result in zip(task_list, results):
                    if isinstance(result, Exception):
                        continue
                    for f in result:
                        dep_date = f['departureTime'].date()
                        if dep_date < dt_from or dep_date > dt_to:
                            continue
                        if f['price'] <= max_price_per_leg:
                            f['_dest_name'] = name
                            f['_country'] = country
                            all_flights.append(f)

                seen = set()
                unique = []
                for f in all_flights:
                    k = (f['flightNumber'], f['departureTime'])
                    if k not in seen:
                        seen.add(k)
                        unique.append(f)
                unique.sort(key=lambda x: x['price'])

                # Сохраняем в кэш (без only_dests если это полный набор)
                if only_dests is None:
                    flights_cache[cache_key] = unique
                    return [f for f in unique if f['destination'] not in visited]
                else:
                    return [f for f in unique if f['destination'] not in visited]

            # ══════════════════════════════════════════════════════
            # ФАЗА 1: Forward BFS с ограничением последнего хопа
            # ══════════════════════════════════════════════════════

            # Первый хоп из origin
            is_single_hop = (hops == 1)
            first_filter = returnable_set if is_single_hop else None
            first_flights = await get_flights_from(origin, departure_date, departure_date,
                                                    {origin}, only_dests=first_filter)
            first_flights = first_flights[:top_n * 3]

            if is_single_hop:
                print(f"[nomad] 1-hop mode: {len(first_flights)} flights to returnable cities")

            partial_routes = []
            for f in first_flights:
                arr_date = f['arrivalTime'].strftime('%Y-%m-%d')
                leg = {
                    'flight': f, 'dest': f['destination'],
                    'dest_name': f.get('_dest_name', f['destination']),
                    'country': f.get('_country', ''),
                    'arrival_date': arr_date,
                }
                partial_routes.append(([leg], f['price'], {origin, f['destination']}))

            # Промежуточные хопы
            for hop_idx in range(1, hops):
                is_last_hop = (hop_idx == hops - 1)
                next_routes = []

                by_airport_date = {}
                for route_idx, (legs, total, visited) in enumerate(partial_routes):
                    last = legs[-1]
                    for stay in nights_per_city:
                        dep_dt = datetime.strptime(last['arrival_date'], '%Y-%m-%d') + timedelta(days=stay)
                        dep_date = dep_dt.strftime('%Y-%m-%d')
                        key = (last['dest'], dep_date, dep_date)
                        if key not in by_airport_date:
                            by_airport_date[key] = []
                        by_airport_date[key].append((route_idx, stay))

                # Fetch рейсы. На последнем хопе — только в returnable аэропорты.
                hop_filter = returnable_set if is_last_hop else None
                fetch_tasks = {}
                for key in by_airport_date:
                    airport, df, dt = key
                    fetch_tasks[key] = get_flights_from(airport, df, dt, set(), only_dests=hop_filter)

                fetched = {}
                keys_list = list(fetch_tasks.keys())
                results = await asyncio.gather(*[fetch_tasks[k] for k in keys_list], return_exceptions=True)
                for k, r in zip(keys_list, results):
                    fetched[k] = r if not isinstance(r, Exception) else []

                if is_last_hop:
                    total_filtered = sum(len(v) for v in fetched.values())
                    print(f"[nomad] Last hop: {total_filtered} flights to returnable cities only")

                for key, route_indices in by_airport_date.items():
                    flights = fetched.get(key, [])
                    for route_idx, stay in route_indices:
                        legs, total, visited = partial_routes[route_idx]
                        for f in flights[:top_n]:
                            if f['destination'] in visited:
                                continue
                            arr_date = f['arrivalTime'].strftime('%Y-%m-%d')
                            new_leg = {
                                'flight': f, 'dest': f['destination'],
                                'dest_name': f.get('_dest_name', f['destination']),
                                'country': f.get('_country', ''),
                                'arrival_date': arr_date,
                            }
                            new_legs = legs + [new_leg]
                            new_legs[-2] = {**new_legs[-2], 'stay_nights': stay}
                            next_routes.append((new_legs, total + f['price'], visited | {f['destination']}))

                next_routes.sort(key=lambda x: x[1])
                partial_routes = next_routes[:top_n * 20]

            if not partial_routes:
                return []

            print(f"[nomad] {len(partial_routes)} routes to validate return flights for")

            # ══════════════════════════════════════════════════════
            # ФАЗА 2: Поиск обратных рейсов (только для маршрутов,
            # заканчивающихся в returnable аэропортах)
            # ══════════════════════════════════════════════════════

            return_tasks = {}
            for idx, (legs, total, visited) in enumerate(partial_routes):
                last = legs[-1]
                for stay in nights_per_city:
                    dep_dt = datetime.strptime(last['arrival_date'], '%Y-%m-%d') + timedelta(days=stay)
                    dep_date = dep_dt.strftime('%Y-%m-%d')
                    key = (last['dest'], dep_date)
                    if key not in return_tasks:
                        return_tasks[key] = None

            async def fetch_return(airport, date):
                batches = self._build_date_batches(date, date)
                tasks = []
                for batch_date, batch_flex in batches:
                    tasks.append(self._fetch_flights(client, sem, airport, origin, '',
                                                     batch_date, flex_days_out=batch_flex))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                flights = []
                target_date = datetime.strptime(date, '%Y-%m-%d').date()
                for r in results:
                    if isinstance(r, Exception):
                        continue
                    for f in r:
                        if f['departureTime'].date() == target_date and f['price'] <= max_price_per_leg:
                            flights.append(f)
                flights.sort(key=lambda x: x['price'])
                return flights

            print(f"[nomad] Fetching return flights for {len(return_tasks)} (airport, date) pairs")
            ret_keys = list(return_tasks.keys())
            ret_results = await asyncio.gather(*[fetch_return(k[0], k[1]) for k in ret_keys],
                                               return_exceptions=True)
            for k, r in zip(ret_keys, ret_results):
                return_tasks[k] = r if not isinstance(r, Exception) else []

            # ══════════════════════════════════════════════════════
            # ФАЗА 3: Собираем полные маршруты с возвратом
            # ══════════════════════════════════════════════════════

            complete_routes = []
            for legs, total, visited in partial_routes:
                last = legs[-1]
                best_return = None
                best_stay = None
                for stay in nights_per_city:
                    dep_dt = datetime.strptime(last['arrival_date'], '%Y-%m-%d') + timedelta(days=stay)
                    dep_date = dep_dt.strftime('%Y-%m-%d')
                    key = (last['dest'], dep_date)
                    ret_flights = return_tasks.get(key, [])
                    if ret_flights:
                        cheapest = ret_flights[0]
                        if best_return is None or cheapest['price'] < best_return['price']:
                            best_return = cheapest
                            best_stay = stay

                if not best_return:
                    continue  # Бидирекциональность не сработала — отсекаем

                final_legs = list(legs)
                final_legs[-1] = {**final_legs[-1], 'stay_nights': best_stay}
                final_total = total + best_return['price']

                complete_routes.append({
                    'legs': final_legs,
                    'return_flight': best_return,
                    'total_price': round(final_total, 2),
                    'currency': self.config['currency'],
                })

            print(f"[nomad] {len(complete_routes)} complete routes with return")

            complete_routes.sort(key=lambda x: x['total_price'])
            seen_routes = set()
            unique_routes = []
            for route in complete_routes:
                cities = tuple(l['dest'] for l in route['legs'])
                price_bucket = round(route['total_price'])
                key = (cities, price_bucket)
                if key not in seen_routes:
                    seen_routes.add(key)
                    unique_routes.append(route)
                if len(unique_routes) >= top_n:
                    break

            # Сериализация
            serialized = []
            for route in unique_routes:
                legs_ser = []
                for leg in route['legs']:
                    f = leg['flight']
                    legs_ser.append({
                        'destination': leg['dest'],
                        'destination_name': leg['dest_name'],
                        'country': leg['country'],
                        'flight_number': f['flightNumber'],
                        'departure_time': f['departureTime'].isoformat(),
                        'arrival_time': f['arrivalTime'].isoformat(),
                        'price': f['price'],
                        'currency': f['currency'],
                        'stay_nights': leg.get('stay_nights', min_nights),
                    })
                rf = route['return_flight']
                serialized.append({
                    'origin': origin,
                    'legs': legs_ser,
                    'return_flight': {
                        'flight_number': rf['flightNumber'],
                        'departure_time': rf['departureTime'].isoformat(),
                        'arrival_time': rf['arrivalTime'].isoformat(),
                        'price': rf['price'],
                        'currency': rf['currency'],
                    },
                    'total_price': route['total_price'],
                    'currency': route['currency'],
                })
            return serialized

    # ── Output ────────────────────────────────────────────────

    def print_one_day_results(self, trips: List[Dict]):
        if not trips:
            print("\nНе найдено подходящих однодневных вариантов.")
            return

        print(f"\nНайдено {len(trips)} однодневных вариантов:\n")

        for i, trip in enumerate(trips, 1):
            outbound = trip['outbound']
            inbound = trip['inbound']
            out_dep = outbound['departureTime']
            out_arr = outbound['arrivalTime']
            in_dep = inbound['departureTime']
            in_arr = inbound['arrivalTime']
            destination_name = outbound.get('destinationName', outbound['destination'])
            destination_code = outbound['destination']
            price = trip['totalPrice']
            stay_hours = trip.get('stay_duration_hours', 0)
            same_day_label = " (в тот же день)" if out_dep.date() == in_arr.date() else " (с ночевкой)"

            print(f"{i}. {destination_name} ({destination_code}) - {price} {self.config['currency']}{same_day_label}")
            print(f"   Туда:    {out_dep.strftime('%d.%m.%Y %H:%M')} → {out_arr.strftime('%H:%M')}")
            print(f"   Обратно: {in_dep.strftime('%d.%m.%Y %H:%M')} → {in_arr.strftime('%H:%M')}")
            print(f"   Время в городе: {stay_hours} часов")
            print(f"   Рейсы: {outbound['flightNumber']} / {inbound['flightNumber']}")
            print()

    def print_results(self, trips: List[Dict], nights: int):
        if not trips:
            print(f"Не найдено подходящих рейсов на {nights} ноч.")
            return

        print(f"\nНайдено {len(trips)} рейс(ов) на {nights} ноч.:\n")

        for i, trip in enumerate(trips, 1):
            outbound = trip['outbound']
            inbound = trip['inbound']
            out_dep = outbound['departureTime']
            out_arr = outbound['arrivalTime']
            in_dep = inbound['departureTime']
            in_arr = inbound['arrivalTime']
            destination_name = outbound.get('destinationName', outbound['destination'])
            destination_code = outbound['destination']
            price = trip['totalPrice']
            stay_hours = trip.get('stay_duration_hours', 0)

            print(f"{i}. {destination_name} ({destination_code}) - {price} {self.config['currency']}")
            print(f"   Туда:    {out_dep.strftime('%d.%m.%Y %H:%M')} → {out_arr.strftime('%H:%M')}")
            print(f"   Обратно: {in_dep.strftime('%d.%m.%Y %H:%M')} → {in_arr.strftime('%H:%M')}")
            print(f"   Длительность:  {stay_hours} часов ({stay_hours/24:.1f} дней)")
            print(f"   Рейсы: {outbound['flightNumber']} / {inbound['flightNumber']}")
            print()
