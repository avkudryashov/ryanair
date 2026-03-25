"""Nomad-маршрутизация: multi-city поиск с BFS и возвратом."""
from datetime import datetime, timedelta
import asyncio

import httpx
import structlog

from models import Flight, Destination
from flight_search.client import RyanairClient
from flight_search.utils import deduplicate_flights, filter_excluded, build_exclusion_sets

log = structlog.get_logger()


class NomadSearcher:
    """Поиск nomad-маршрутов: options, routes, return."""

    def __init__(self, client: RyanairClient, config: dict):
        self.client = client
        self.config = config

    async def async_search_nomad_options(
        self, origin, date_from, date_to, max_price_per_leg, top_n,
        excluded_airports, excluded_countries,
    ) -> list[dict]:
        excluded_ap, excluded_co = build_exclusion_sets(self.config, excluded_airports, excluded_countries)

        sem = asyncio.Semaphore(self.client.MAX_CONCURRENCY)

        async with self.client.get_client() as http:
            dest_params = {
                "departureAirportIataCode": origin,
                "outboundDepartureDateFrom": date_from,
                "outboundDepartureDateTo": date_to,
                "currency": self.config['currency'],
            }
            destinations = await self.client.fetch_destinations(http, dest_params)
            destinations = filter_excluded(destinations, excluded_ap, excluded_co)

            if not destinations:
                return []

            # Шаг 2: рейсы параллельно (батчами)
            batches = self.client.build_date_batches(date_from, date_to)
            task_list = []
            for dest, info in destinations.items():
                for batch_date, batch_flex in batches:
                    task_list.append((
                        dest, info.name, info.country,
                        self.client.fetch_flights(http, sem, origin, dest, info.name,
                                                  batch_date, flex_days_out=batch_flex)
                    ))

            results = await asyncio.gather(
                *[t[3] for t in task_list], return_exceptions=True
            )

            # Собираем все рейсы, фильтруем по дате и цене
            dt_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            all_flights: list[Flight] = []
            dest_info = {}
            for (dest, name, country, _), result in zip(task_list, results):
                dest_info[dest] = {'name': name, 'country': country}
                if isinstance(result, Exception):
                    continue
                for f in result:
                    dep_date = f.departure_time.date()
                    if dep_date < dt_from or dep_date > dt_to:
                        continue
                    if f.price <= max_price_per_leg:
                        all_flights.append(f)

            unique = deduplicate_flights(all_flights)
            unique.sort(key=lambda x: x.price)
            top = unique[:top_n]

            # Сериализуем для JSON
            serialized = []
            for f in top:
                serialized.append({
                    'destination': f.destination,
                    'destination_name': f.destination_name or f.destination,
                    'country': dest_info.get(f.destination, {}).get('country', ''),
                    'flight_number': f.flight_number,
                    'departure_time': f.departure_time.isoformat(),
                    'arrival_time': f.arrival_time.isoformat(),
                    'price': f.price,
                    'currency': f.currency,
                })
            return serialized

    async def async_search_nomad_return(
        self, origin, destination, date_from, date_to, max_price,
    ) -> list[dict]:
        sem = asyncio.Semaphore(self.client.MAX_CONCURRENCY)

        async with self.client.get_client() as http:
            batches = self.client.build_date_batches(date_from, date_to)

            task_list = []
            for batch_date, batch_flex in batches:
                task_list.append(
                    self.client.fetch_flights(http, sem, origin, destination, '',
                                              batch_date, flex_days_out=batch_flex)
                )

            results = await asyncio.gather(*task_list, return_exceptions=True)

            dt_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            all_flights: list[Flight] = []
            for result in results:
                if isinstance(result, Exception):
                    continue
                for f in result:
                    dep_date = f.departure_time.date()
                    if dep_date < dt_from or dep_date > dt_to:
                        continue
                    if f.price <= max_price:
                        all_flights.append(f)

            unique = deduplicate_flights(all_flights)
            unique.sort(key=lambda x: (x.price, x.departure_time))

            serialized = []
            for f in unique:
                serialized.append({
                    'destination': f.destination,
                    'destination_name': f.destination_name or f.destination,
                    'flight_number': f.flight_number,
                    'departure_time': f.departure_time.isoformat(),
                    'arrival_time': f.arrival_time.isoformat(),
                    'price': f.price,
                    'currency': f.currency,
                })
            return serialized

    async def async_search_nomad_routes(
        self, origin, departure_date, hops, nights_per_city,
        max_price_per_leg, top_n, excluded_airports, excluded_countries,
    ) -> list[dict]:
        min_nights = min(nights_per_city)
        max_nights = max(nights_per_city)

        excluded_ap, excluded_co = build_exclusion_sets(self.config, excluded_airports, excluded_countries)

        sem = asyncio.Semaphore(self.client.MAX_CONCURRENCY)

        async with self.client.get_client() as http:

            # ══════════════════════════════════════════════════════
            # ФАЗА 0: Вычисляем returnable_set
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
            returnable_dests = await self.client.fetch_destinations(http, ret_dest_params)
            returnable_set = set(returnable_dests.keys())
            returnable_set -= excluded_ap
            if excluded_co:
                returnable_set = {c for c in returnable_set
                                  if returnable_dests[c].country not in excluded_co}

            log.info("nomad_returnable", origin=origin, count=len(returnable_set))
            if not returnable_set:
                log.warning("nomad_no_returnable", origin=origin)
                return []

            # ══════════════════════════════════════════════════════
            # Кэш рейсов + helper
            # ══════════════════════════════════════════════════════

            flights_cache: dict[tuple, list[Flight]] = {}

            async def get_flights_from(airport, date_from, date_to, visited, only_dests=None):
                cache_key = (airport, date_from, date_to)
                use_full_cache = only_dests is None and cache_key in flights_cache

                if use_full_cache:
                    return [f for f in flights_cache[cache_key]
                            if f.destination not in visited]

                if only_dests is not None and cache_key in flights_cache:
                    return [f for f in flights_cache[cache_key]
                            if f.destination not in visited and f.destination in only_dests]

                dest_params = {
                    "departureAirportIataCode": airport,
                    "outboundDepartureDateFrom": date_from,
                    "outboundDepartureDateTo": date_to,
                    "currency": self.config['currency'],
                }
                destinations = await self.client.fetch_destinations(http, dest_params)
                destinations = filter_excluded(destinations, excluded_ap, excluded_co)
                if only_dests is not None:
                    destinations = {c: i for c, i in destinations.items() if c in only_dests}

                batches = self.client.build_date_batches(date_from, date_to)
                task_list = []
                for dest, info in destinations.items():
                    for batch_date, batch_flex in batches:
                        task_list.append((
                            dest, info.name, info.country,
                            self.client.fetch_flights(http, sem, airport, dest, info.name,
                                                      batch_date, flex_days_out=batch_flex)
                        ))

                results = await asyncio.gather(*[t[3] for t in task_list], return_exceptions=True)

                dt_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                dt_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                all_flights: list[Flight] = []
                for (dest, name, country, _), result in zip(task_list, results):
                    if isinstance(result, Exception):
                        continue
                    for f in result:
                        dep_date = f.departure_time.date()
                        if dep_date < dt_from or dep_date > dt_to:
                            continue
                        if f.price <= max_price_per_leg:
                            f = f.model_copy(update={'dest_name': name, 'country_name': country})
                            all_flights.append(f)

                unique = deduplicate_flights(all_flights)
                unique.sort(key=lambda x: x.price)

                if only_dests is None:
                    flights_cache[cache_key] = unique
                    return [f for f in unique if f.destination not in visited]
                else:
                    return [f for f in unique if f.destination not in visited]

            # ══════════════════════════════════════════════════════
            # ФАЗА 1: Forward BFS с ограничением последнего хопа
            # ══════════════════════════════════════════════════════

            is_single_hop = (hops == 1)
            first_filter = returnable_set if is_single_hop else None
            first_flights = await get_flights_from(origin, departure_date, departure_date,
                                                    {origin}, only_dests=first_filter)
            first_flights = first_flights[:top_n * 3]

            if is_single_hop:
                log.info("nomad_1hop", flights=len(first_flights))

            partial_routes = []
            for f in first_flights:
                arr_date = f.arrival_time.strftime('%Y-%m-%d')
                leg = {
                    'flight': f, 'dest': f.destination,
                    'dest_name': f.dest_name or f.destination,
                    'country': f.country_name,
                    'arrival_date': arr_date,
                }
                partial_routes.append(([leg], f.price, {origin, f.destination}))

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
                    log.info("nomad_last_hop", flights=total_filtered)

                for key, route_indices in by_airport_date.items():
                    flights = fetched.get(key, [])
                    for route_idx, stay in route_indices:
                        legs, total, visited = partial_routes[route_idx]
                        for f in flights[:top_n]:
                            if f.destination in visited:
                                continue
                            arr_date = f.arrival_time.strftime('%Y-%m-%d')
                            new_leg = {
                                'flight': f, 'dest': f.destination,
                                'dest_name': f.dest_name or f.destination,
                                'country': f.country_name,
                                'arrival_date': arr_date,
                            }
                            new_legs = legs + [new_leg]
                            new_legs[-2] = {**new_legs[-2], 'stay_nights': stay}
                            next_routes.append((new_legs, total + f.price, visited | {f.destination}))

                next_routes.sort(key=lambda x: x[1])
                partial_routes = next_routes[:top_n * 20]

            if not partial_routes:
                return []

            log.info("nomad_validating_returns", routes=len(partial_routes))

            # ══════════════════════════════════════════════════════
            # ФАЗА 2: Поиск обратных рейсов
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
                batches = self.client.build_date_batches(date, date)
                tasks = []
                for batch_date, batch_flex in batches:
                    tasks.append(self.client.fetch_flights(http, sem, airport, origin, '',
                                                           batch_date, flex_days_out=batch_flex))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                flights: list[Flight] = []
                target_date = datetime.strptime(date, '%Y-%m-%d').date()
                for r in results:
                    if isinstance(r, Exception):
                        continue
                    for f in r:
                        if f.departure_time.date() == target_date and f.price <= max_price_per_leg:
                            flights.append(f)
                flights.sort(key=lambda x: x.price)
                return flights

            log.info("nomad_fetching_returns", pairs=len(return_tasks))
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
                        if best_return is None or cheapest.price < best_return.price:
                            best_return = cheapest
                            best_stay = stay

                if not best_return:
                    continue

                final_legs = list(legs)
                final_legs[-1] = {**final_legs[-1], 'stay_nights': best_stay}
                final_total = total + best_return.price

                complete_routes.append({
                    'legs': final_legs,
                    'return_flight': best_return,
                    'total_price': round(final_total, 2),
                    'currency': self.config['currency'],
                })

            log.info("nomad_complete_routes", count=len(complete_routes))

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
                        'flight_number': f.flight_number,
                        'departure_time': f.departure_time.isoformat(),
                        'arrival_time': f.arrival_time.isoformat(),
                        'price': f.price,
                        'currency': f.currency,
                        'stay_nights': leg.get('stay_nights', min_nights),
                    })
                rf = route['return_flight']
                serialized.append({
                    'origin': origin,
                    'legs': legs_ser,
                    'return_flight': {
                        'flight_number': rf.flight_number,
                        'departure_time': rf.departure_time.isoformat(),
                        'arrival_time': rf.arrival_time.isoformat(),
                        'price': rf.price,
                        'currency': rf.currency,
                    },
                    'total_price': route['total_price'],
                    'currency': route['currency'],
                })
            return serialized
