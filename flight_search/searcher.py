"""
Модуль для поиска дешевых рейсов через прямые запросы к API Ryanair.
Использует httpx async для параллельных запросов и diskcache (SQLite) с stale-while-revalidate.
"""
from datetime import datetime, timedelta
import yaml
import asyncio

import httpx
import structlog

from flight_search.cache import SWRCache
from flight_search.client import RyanairClient
from flight_search.nomad import NomadSearcher
from flight_search.utils import deduplicate_flights, filter_excluded, build_exclusion_sets
from models import Flight, Trip, Destination

log = structlog.get_logger()


class FlightSearcher:
    """Класс для поиска рейсов через асинхронные запросы к API Ryanair."""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        self._cache = SWRCache()
        self._client = RyanairClient(self._cache, self.config)
        self._nomad = NomadSearcher(self._client, self.config)

    # ── Lifecycle ─────────────────────────────────────────────

    async def open(self):
        await self._client.open()

    async def close(self):
        await self._client.close()

    # ── Airports ──────────────────────────────────────────────

    def get_airports(self) -> list[dict]:
        return self._client.get_airports()

    # ── Data freshness ────────────────────────────────────────

    def get_data_freshness(self) -> dict:
        return self._client.get_data_freshness()

    # ── Cache stats ───────────────────────────────────────────

    def cache_stats(self) -> dict:
        return self._cache.stats()

    # ── Main search (regular) ─────────────────────────────────

    def search_flights(
        self,
        departure_date: str,
        nights: list[int],
        excluded_airports_override: list[str] = None,
        excluded_countries_override: list[str] = None,
        origin_override: str = None,
        flex_days_override: int = None,
        max_price_override: int = None,
        destination_override: str = None,
    ) -> list[Trip]:
        """Синхронная обёртка для async поиска рейсов."""
        self._client.reset_stale_flag()
        return asyncio.run(self.async_search_flights(
            departure_date, nights,
            origin=origin_override,
            excluded_airports=excluded_airports_override,
            excluded_countries=excluded_countries_override,
            flex_days=flex_days_override,
            max_price=max_price_override,
            destination=destination_override,
        ))

    async def async_search_flights(self, departure_date, nights, *, origin=None,
                                    excluded_airports=None, excluded_countries=None,
                                    flex_days=None, max_price=None, destination=None):
        origin = origin or self.config['origin_airport']
        all_results = []

        excluded_ap, excluded_co = build_exclusion_sets(self.config, excluded_airports, excluded_countries)

        date_flexibility = flex_days if flex_days is not None else self.config.get('date_flexibility_days', 0)
        departure_dt = datetime.strptime(departure_date, '%Y-%m-%d')

        outbound_date_from = (departure_dt - timedelta(days=date_flexibility)).strftime('%Y-%m-%d')
        outbound_date_to = (departure_dt + timedelta(days=date_flexibility)).strftime('%Y-%m-%d')

        max_nights = max(nights)
        min_nights = min(nights)
        return_date_from = (departure_dt - timedelta(days=date_flexibility) + timedelta(days=min_nights)).strftime('%Y-%m-%d')
        return_date_to = (departure_dt + timedelta(days=date_flexibility + max_nights + 1)).strftime('%Y-%m-%d')

        log.info("search_params", date=departure_date, flex=date_flexibility, nights=nights,
                 outbound=f"{outbound_date_from}..{outbound_date_to}",
                 return_range=f"{return_date_from}..{return_date_to}")

        sem = asyncio.Semaphore(self._client.MAX_CONCURRENCY)

        async with self._client.get_client() as client:
            # Шаг 1: направления
            log.info("fetching_destinations", origin=origin)
            dest_params = {
                "departureAirportIataCode": origin,
                "outboundDepartureDateFrom": outbound_date_from,
                "outboundDepartureDateTo": outbound_date_to,
                "currency": self.config['currency']
            }
            destinations = await self._client.fetch_destinations(client, dest_params)

            destinations = filter_excluded(destinations, excluded_ap, excluded_co)

            # Фильтрация по конкретному направлению
            if destination:
                dest_upper = destination.upper()
                destinations = {c: i for c, i in destinations.items() if c == dest_upper}

            log.info("destinations_found", count=len(destinations))
            if not destinations:
                return []

            # Шаг 2: все рейсы ТУДА — параллельно (батчами если диапазон > 6 дней)
            out_batches = self._client.build_date_batches(outbound_date_from, outbound_date_to)
            log.info("fetching_outbound", destinations=len(destinations), batches=len(out_batches))

            outbound_task_list = []
            for dest, info in destinations.items():
                for batch_date, batch_flex in out_batches:
                    outbound_task_list.append((
                        dest,
                        self._client.fetch_flights(client, sem, origin, dest, info.name, batch_date, flex_days_out=batch_flex)
                    ))

            outbound_results = await asyncio.gather(
                *[t[1] for t in outbound_task_list], return_exceptions=True
            )
            outbound_flights_by_dest = {}
            for (dest, _), result in zip(outbound_task_list, outbound_results):
                if isinstance(result, Exception):
                    if not (isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 400):
                        log.warning("outbound_fetch_error", dest=dest, error=str(result))
                elif result:
                    outbound_flights_by_dest.setdefault(dest, []).extend(result)

            for dest in outbound_flights_by_dest:
                outbound_flights_by_dest[dest] = deduplicate_flights(outbound_flights_by_dest[dest])

            total_out = sum(len(f) for f in outbound_flights_by_dest.values())
            log.info("outbound_flights_total", count=total_out)

            # Шаг 3: все обратные рейсы — параллельно (батчами)
            ret_batches = self._client.build_date_batches(return_date_from, return_date_to)
            log.info("fetching_inbound", destinations=len(outbound_flights_by_dest),
                     batches=len(ret_batches), range=f"{return_date_from}..{return_date_to}")

            inbound_task_list = []
            for dest in outbound_flights_by_dest:
                dest_name = destinations[dest].name if dest in destinations else dest
                for batch_date, batch_flex in ret_batches:
                    inbound_task_list.append((
                        dest,
                        self._client.fetch_flights(client, sem, dest, origin, dest_name, batch_date, flex_days_out=batch_flex)
                    ))

            inbound_results = await asyncio.gather(
                *[t[1] for t in inbound_task_list], return_exceptions=True
            )
            inbound_flights_by_dest = {}
            for (dest, _), result in zip(inbound_task_list, inbound_results):
                if isinstance(result, Exception):
                    if not (isinstance(result, httpx.HTTPStatusError) and result.response.status_code == 400):
                        log.warning("inbound_fetch_error", dest=dest, error=str(result))
                elif result:
                    inbound_flights_by_dest.setdefault(dest, []).extend(result)

            for dest in inbound_flights_by_dest:
                inbound_flights_by_dest[dest] = deduplicate_flights(inbound_flights_by_dest[dest])

            total_in = sum(len(f) for f in inbound_flights_by_dest.values())
            log.info("inbound_flights_total", count=total_in)

        # Шаг 4: комбинируем
        effective_max_price = max_price if max_price is not None else self.config['max_price']
        for night_count in nights:
            filtered_trips = self._combine_flights(
                outbound_flights_by_dest, inbound_flights_by_dest, night_count,
                max_price=effective_max_price
            )
            filtered_trips.sort(key=lambda x: x.total_price)
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
                arrival_hour = outbound.arrival_time.time().replace(second=0, microsecond=0)
                if arrival_hour > max_arrival_time:
                    rejected_late += len(inbound_list)
                    total += len(inbound_list)
                    continue

                for inbound in inbound_list:
                    total += 1
                    stay_duration = (inbound.departure_time - outbound.arrival_time).total_seconds() / 3600

                    if night_count == 1:
                        min_hours = self.config['min_hours_for_one_night']
                        if stay_duration < min_hours:
                            rejected_min_h += 1
                            continue

                    calendar_nights = (inbound.departure_time.date() - outbound.arrival_time.date()).days
                    if calendar_nights != night_count:
                        rejected_dur += 1
                        continue

                    total_price = outbound.price + inbound.price
                    if total_price > max_price:
                        rejected_price += 1
                        continue

                    filtered.append(Trip(
                        total_price=total_price,
                        outbound=outbound,
                        inbound=inbound,
                        nights=night_count,
                        stay_duration_hours=round(stay_duration, 1),
                        destination_full=dest
                    ))

        log.info("combine_results", nights=night_count, checked=total, late=rejected_late,
                 duration=rejected_dur, min_hours=rejected_min_h, price=rejected_price,
                 matched=len(filtered))
        return filtered

    # ── One-day trips ─────────────────────────────────────────

    def search_one_day_trips(
        self,
        excluded_airports_override: list[str] = None,
        excluded_countries_override: list[str] = None,
        origin_override: str = None,
        max_price_override: int = None
    ) -> list[Trip]:
        """Синхронная обёртка для async поиска однодневных поездок."""
        self._client.reset_stale_flag()
        return asyncio.run(self.async_search_one_day_trips(
            origin=origin_override,
            excluded_airports=excluded_airports_override,
            excluded_countries=excluded_countries_override,
            max_price=max_price_override,
        ))

    async def async_search_one_day_trips(self, *, origin=None,
                                          excluded_airports=None, excluded_countries=None,
                                          max_price=None):
        origin = origin or self.config['origin_airport']
        max_price = max_price if max_price is not None else self.config['max_price']
        all_results = []

        excluded_ap, excluded_co = build_exclusion_sets(self.config, excluded_airports, excluded_countries)

        today = datetime.now().date()
        start_date = today + timedelta(days=1)
        end_date = today + timedelta(days=60)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        log.info("one_day_search", date_from=start_date_str, date_to=end_date_str)

        sem = asyncio.Semaphore(self._client.MAX_CONCURRENCY)

        async with self._client.get_client() as client:
            # Шаг 1: направления
            log.info("fetching_destinations", origin=origin)
            dest_params = {
                "departureAirportIataCode": origin,
                "outboundDepartureDateFrom": start_date_str,
                "outboundDepartureDateTo": end_date_str,
                "currency": self.config['currency']
            }
            destinations = await self._client.fetch_destinations(client, dest_params)
            destinations = filter_excluded(destinations, excluded_ap, excluded_co)

            log.info("destinations_found", count=len(destinations))
            if not destinations:
                return []

            # Шаг 2: для каждого направления — запрашиваем рейсы батчами по неделям
            log.info("fetching_flights_batched")

            batch_centers = []
            current = start_date + timedelta(days=3)
            while current <= end_date:
                batch_centers.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=7)

            outbound_tasks = []
            for dest, info in destinations.items():
                for center_date in batch_centers:
                    outbound_tasks.append((
                        dest, info.name, center_date,
                        self._client.fetch_flights(client, sem, origin, dest, info.name, center_date, flex_days_out=6)
                    ))

            log.info("outbound_requests", count=len(outbound_tasks), concurrency=self._client.MAX_CONCURRENCY)

            outbound_results = await asyncio.gather(
                *[t[3] for t in outbound_tasks], return_exceptions=True
            )

            morning_flights_by_dest = {}
            for (dest, name, center, _), result in zip(outbound_tasks, outbound_results):
                if isinstance(result, Exception):
                    continue
                for f in result:
                    if f.departure_time.time().hour < 12:
                        morning_flights_by_dest.setdefault(dest, []).append(f)

            for dest in morning_flights_by_dest:
                morning_flights_by_dest[dest] = deduplicate_flights(morning_flights_by_dest[dest])

            total_morning = sum(len(v) for v in morning_flights_by_dest.values())
            log.info("morning_flights_found", count=total_morning, destinations=len(morning_flights_by_dest))

            # Шаг 3: обратные рейсы — тоже батчами
            return_tasks = []
            for dest in morning_flights_by_dest:
                dest_name = destinations[dest].name if dest in destinations else dest
                for center_date in batch_centers:
                    return_tasks.append((
                        dest, center_date,
                        self._client.fetch_flights(client, sem, dest, origin, dest_name, center_date, flex_days_out=6)
                    ))

            log.info("return_requests", count=len(return_tasks))

            return_results = await asyncio.gather(
                *[t[2] for t in return_tasks], return_exceptions=True
            )

            evening_returns_by_dest = {}
            for (dest, center, _), result in zip(return_tasks, return_results):
                if isinstance(result, Exception):
                    continue
                for f in result:
                    if f.arrival_time.time().hour >= 18:
                        evening_returns_by_dest.setdefault(dest, []).append(f)

            for dest in evening_returns_by_dest:
                evening_returns_by_dest[dest] = deduplicate_flights(evening_returns_by_dest[dest])

            total_evening = sum(len(v) for v in evening_returns_by_dest.values())
            log.info("evening_return_flights", count=total_evening)

        # Шаг 4: комбинируем
        for dest, outbound_list in morning_flights_by_dest.items():
            inbound_list = evening_returns_by_dest.get(dest, [])
            if not inbound_list:
                continue

            for outbound in outbound_list:
                for inbound in inbound_list:
                    if outbound.departure_time.date() == inbound.arrival_time.date():
                        continue

                    stay_duration = (inbound.departure_time - outbound.arrival_time).total_seconds() / 3600
                    if stay_duration < 6 or stay_duration > 36:
                        continue

                    total_price = outbound.price + inbound.price
                    if total_price > max_price:
                        continue

                    all_results.append(Trip(
                        total_price=total_price,
                        outbound=outbound,
                        inbound=inbound,
                        nights=1,
                        stay_duration_hours=round(stay_duration, 1),
                        destination_full=dest
                    ))

        all_results.sort(key=lambda x: x.total_price)
        max_results = self.config['max_results']
        limited = all_results[:max_results]
        self.print_one_day_results(limited)
        return limited

    # ── Sync wrappers for backward compatibility ──────────────

    async def async_get_available_destinations(self, origin: str, date_from: str, date_to: str) -> dict[str, Destination]:
        """Async получение направлений (для FastAPI / warm cache)."""
        async with self._client.get_client() as client:
            params = {
                "departureAirportIataCode": origin,
                "outboundDepartureDateFrom": date_from,
                "outboundDepartureDateTo": date_to,
                "currency": self.config['currency'],
            }
            return await self._client.fetch_destinations(client, params)

    def get_available_destinations(self, date_from: str, date_to: str, *, origin: str = None) -> dict[str, Destination]:
        """Sync wrapper over async_get_available_destinations."""
        origin = origin or self.config['origin_airport']
        return asyncio.run(self.async_get_available_destinations(origin, date_from, date_to))

    # ── Nomad delegations ─────────────────────────────────────

    def search_nomad_options(
        self, origin, date_from, date_to,
        max_price_per_leg=50, top_n=10,
        excluded_airports=None, excluded_countries=None,
    ) -> list[dict]:
        self._client.reset_stale_flag()
        return asyncio.run(self.async_search_nomad_options(
            origin, date_from, date_to, max_price_per_leg, top_n,
            excluded_airports, excluded_countries,
        ))

    async def async_search_nomad_options(self, origin, date_from, date_to,
                                          max_price_per_leg, top_n,
                                          excluded_airports, excluded_countries) -> list[dict]:
        return await self._nomad.async_search_nomad_options(
            origin, date_from, date_to, max_price_per_leg, top_n,
            excluded_airports, excluded_countries,
        )

    def search_nomad_return(self, origin, destination, date_from, date_to, max_price=50) -> list[dict]:
        self._client.reset_stale_flag()
        return asyncio.run(self.async_search_nomad_return(
            origin, destination, date_from, date_to, max_price,
        ))

    async def async_search_nomad_return(self, origin, destination, date_from, date_to, max_price) -> list[dict]:
        return await self._nomad.async_search_nomad_return(
            origin, destination, date_from, date_to, max_price,
        )

    def search_nomad_routes(
        self, origin, departure_date, hops=2, nights_per_city=None,
        max_price_per_leg=50, top_n=10,
        excluded_airports=None, excluded_countries=None,
    ) -> list[dict]:
        self._client.reset_stale_flag()
        if nights_per_city is None:
            nights_per_city = [1, 2, 3]
        hops = max(1, min(hops, 4))
        return asyncio.run(self.async_search_nomad_routes(
            origin, departure_date, hops, nights_per_city,
            max_price_per_leg, top_n,
            excluded_airports, excluded_countries,
        ))

    async def async_search_nomad_routes(
        self, origin, departure_date, hops, nights_per_city,
        max_price_per_leg, top_n, excluded_airports, excluded_countries,
    ) -> list[dict]:
        return await self._nomad.async_search_nomad_routes(
            origin, departure_date, hops, nights_per_city,
            max_price_per_leg, top_n, excluded_airports, excluded_countries,
        )

    # ── Output ────────────────────────────────────────────────

    def print_one_day_results(self, trips: list[Trip]):
        if not trips:
            log.info("no_one_day_results")
            return

        log.info("one_day_results", count=len(trips))
        for i, trip in enumerate(trips, 1):
            outbound = trip.outbound
            inbound = trip.inbound
            log.info("trip", rank=i,
                     dest=outbound.destination_name or outbound.destination,
                     price=trip.total_price, currency=self.config['currency'],
                     out=outbound.departure_time.strftime('%d.%m %H:%M'),
                     ret=inbound.departure_time.strftime('%d.%m %H:%M'),
                     stay_h=trip.stay_duration_hours)

    def print_results(self, trips: list[Trip], nights: int):
        if not trips:
            log.info("no_results", nights=nights)
            return

        log.info("search_results", count=len(trips), nights=nights)
        for i, trip in enumerate(trips, 1):
            outbound = trip.outbound
            inbound = trip.inbound
            log.info("trip", rank=i, nights=nights,
                     dest=outbound.destination_name or outbound.destination,
                     price=trip.total_price, currency=self.config['currency'],
                     out=outbound.departure_time.strftime('%d.%m %H:%M'),
                     ret=inbound.departure_time.strftime('%d.%m %H:%M'),
                     stay_h=trip.stay_duration_hours)
