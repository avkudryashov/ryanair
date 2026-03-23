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

    # Максимум параллельных запросов к API
    MAX_CONCURRENCY = 15

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

        # Persistent SQLite кэш (переживает рестарт)
        self._cache = diskcache.Cache(".cache_data", size_limit=256 * 1024 * 1024)

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
        Stale-While-Revalidate чтение из кэша.
        Returns: (data, is_stale)
            data=None если кэш пуст или полностью протух
            is_stale=True если данные устарели но пригодны
        """
        raw = self._cache.get(key)
        if raw is None:
            return None, False
        data, timestamp = raw
        age = time.time() - timestamp
        if age < fresh_ttl:
            return data, False  # свежие
        elif age < stale_ttl:
            return data, True   # stale — отдаём, но нужно обновить
        else:
            return None, False  # полностью протухли

    def _cache_set(self, key: str, data: any, stale_ttl: int):
        """Сохраняет в кэш с timestamp. expire=stale_ttl для автоочистки."""
        self._cache.set(key, (data, time.time()), expire=stale_ttl)

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
        max_price_override: int = None
    ) -> List[Dict]:
        """Синхронная обёртка для async поиска рейсов."""
        self._served_from_stale = False
        original_origin = self.origin
        if origin_override:
            self.origin = origin_override
        try:
            return asyncio.run(self._async_search_flights(
                departure_date, nights, excluded_airports_override,
                excluded_countries_override, flex_days_override, max_price_override
            ))
        finally:
            self.origin = original_origin

    async def _async_search_flights(self, departure_date, nights, excluded_airports_override,
                                     excluded_countries_override=None, flex_days_override=None,
                                     max_price_override=None):
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

        async with httpx.AsyncClient(http2=True) as client:
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

        async with httpx.AsyncClient(http2=True) as client:
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
