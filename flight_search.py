"""
Модуль для поиска дешевых рейсов из Валенсии через прямые запросы к API Ryanair.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import yaml
import requests
import json
import os
import hashlib
import time
import random


class FlightSearcher:
    """Класс для поиска рейсов через прямые запросы к API Ryanair."""

    # API endpoints
    AVAILABILITY_API = "https://www.ryanair.com/api/booking/v4/availability"
    FARFND_API = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"

    # Время жизни кэша в секундах (5 минут)
    CACHE_TTL = 300

    # Список User-Agent для мимикрии под разные браузеры
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
        """
        Инициализация поисковика рейсов.

        Args:
            config_path: путь к файлу конфигурации
        """
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        self.origin = self.config['origin_airport']

        # Создаем директорию для кэша
        self.cache_dir = ".cache"
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def _get_random_headers(self) -> dict:
        """
        Возвращает headers с случайным User-Agent.

        Returns:
            Словарь с headers
        """
        return {
            'User-Agent': random.choice(self.USER_AGENTS),
        }

    def _get_cache_key(self, prefix: str, params: dict) -> str:
        """
        Генерирует ключ кэша на основе параметров запроса.

        Args:
            prefix: префикс для типа запроса
            params: параметры запроса

        Returns:
            Путь к файлу кэша
        """
        # Создаем строку из параметров для хеширования
        params_str = json.dumps(params, sort_keys=True)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{prefix}_{params_hash}.json")

    def _get_from_cache(self, cache_key: str) -> Optional[dict]:
        """
        Получает данные из кэша, если они не устарели.

        Args:
            cache_key: ключ кэша (путь к файлу)

        Returns:
            Данные из кэша или None, если кэш устарел или не существует
        """
        if not os.path.exists(cache_key):
            return None

        try:
            with open(cache_key, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # Проверяем возраст кэша
            cache_time = cache_data.get('timestamp', 0)
            current_time = time.time()

            if current_time - cache_time < self.CACHE_TTL:
                return cache_data.get('data')
            else:
                # Кэш устарел, удаляем файл
                os.remove(cache_key)
                return None
        except Exception:
            return None

    def _save_to_cache(self, cache_key: str, data: any):
        """
        Сохраняет данные в кэш.

        Args:
            cache_key: ключ кэша (путь к файлу)
            data: данные для сохранения
        """
        try:
            cache_data = {
                'timestamp': time.time(),
                'data': data
            }
            with open(cache_key, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"Предупреждение: не удалось сохранить кэш: {e}")

    def get_available_destinations(self, date_from: str, date_to: str) -> Dict[str, Dict]:
        """
        Получает список всех доступных направлений с минимальными ценами и полными названиями.

        Args:
            date_from: начальная дата (YYYY-MM-DD)
            date_to: конечная дата (YYYY-MM-DD)

        Returns:
            Словарь {код_аэропорта: {'price': цена, 'name': полное_название}}
        """
        params = {
            "departureAirportIataCode": self.origin,
            "outboundDepartureDateFrom": date_from,
            "outboundDepartureDateTo": date_to,
            "currency": self.config['currency']
        }

        # Проверяем кэш
        cache_key = self._get_cache_key("destinations", params)
        cached_data = self._get_from_cache(cache_key)
        if cached_data is not None:
            print("  (используется кэш)")
            return cached_data

        try:
            response = requests.get(self.FARFND_API, params=params, headers=self._get_random_headers(), timeout=30)
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

                # Пропускаем исключенные страны
                if dest_country in excluded_countries:
                    continue

                if dest and (dest not in destinations or price < destinations[dest]['price']):
                    destinations[dest] = {
                        'price': price,
                        'name': dest_name,
                        'country': dest_country
                    }

            # Сохраняем в кэш
            self._save_to_cache(cache_key, destinations)

            return destinations

        except Exception as e:
            print(f"Ошибка при получении направлений: {e}")
            return {}

    def get_all_flights_to_destination(
        self,
        destination: str,
        destination_name: str,
        date_out: str,
        flex_days_out: int = 0
    ) -> List[Dict]:
        """
        Получает ВСЕ рейсы в указанное направление через Availability API.

        Args:
            destination: код аэропорта назначения
            destination_name: полное название города/аэропорта
            date_out: дата вылета (YYYY-MM-DD)
            flex_days_out: гибкость дат в днях

        Returns:
            Список всех рейсов с полной информацией
        """
        params = {
            "ADT": 1,  # 1 взрослый
            "CHD": 0,
            "DateOut": date_out,
            "Destination": destination,
            "FlexDaysOut": flex_days_out,
            "INF": 0,
            "Origin": self.origin,
            "RoundTrip": "false",  # Только в одну сторону
            "TEEN": 0,
            "ToUs": "AGREED"
        }

        # Проверяем кэш
        cache_key = self._get_cache_key("flights", params)
        cached_data = self._get_from_cache(cache_key)
        if cached_data is not None:
            print("    (используется кэш)")
            # Восстанавливаем datetime объекты
            for flight in cached_data:
                flight['departureTime'] = datetime.fromisoformat(flight['departureTime'])
                flight['arrivalTime'] = datetime.fromisoformat(flight['arrivalTime'])
            return cached_data

        try:
            response = requests.get(self.AVAILABILITY_API, params=params, headers=self._get_random_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()

            flights = []
            for trip in data.get('trips', []):
                # Получаем полные названия из trip, если доступны
                trip_origin_name = trip.get('originName', self.origin)
                trip_dest_name = trip.get('destinationName', destination_name)

                for date_entry in trip.get('dates', []):
                    for flight in date_entry.get('flights', []):
                        # Извлекаем информацию о рейсе
                        segments = flight.get('segments', [])
                        if not segments:
                            continue

                        segment = segments[0]  # Берем первый сегмент (прямой рейс)
                        times = segment.get('time', [])
                        if len(times) < 2:
                            continue

                        # Извлекаем цену
                        regular_fare = flight.get('regularFare', {})
                        fares = regular_fare.get('fares', [])
                        if not fares:
                            continue

                        price = fares[0].get('amount', float('inf'))

                        # Создаем структуру рейса
                        flight_info = {
                            'origin': segment['origin'],
                            'originName': trip_origin_name,
                            'destination': segment['destination'],
                            'destinationName': trip_dest_name,
                            'departureTime': datetime.fromisoformat(times[0].replace('Z', '+00:00')),
                            'arrivalTime': datetime.fromisoformat(times[1].replace('Z', '+00:00')),
                            'flightNumber': segment['flightNumber'],
                            'price': price,
                            'currency': self.config['currency']
                        }

                        flights.append(flight_info)

            # Сохраняем в кэш (datetime будет сконвертирован в строку через default=str)
            self._save_to_cache(cache_key, flights)

            return flights

        except Exception as e:
            print(f"Ошибка при получении рейсов в {destination}: {e}")
            return []

    def search_flights(
        self,
        departure_date: str,
        nights: List[int],
        excluded_airports_override: List[str] = None
    ) -> List[Dict]:
        """
        Поиск рейсов с учетом всех фильтров.
        Получает ВСЕ рейсы через Availability API и комбинирует их.

        Args:
            departure_date: дата вылета (YYYY-MM-DD)
            nights: список количества ночей для поиска
            excluded_airports_override: список кодов исключенных аэропортов (переопределяет config)

        Returns:
            Список подходящих рейсов
        """
        all_results = []

        # Объединяем исключенные аэропорты из конфига и командной строки
        excluded_airports = set(self.config.get('excluded_airports', []))
        if excluded_airports_override:
            excluded_airports.update(excluded_airports_override)

        # Применяем гибкость по датам вылета
        date_flexibility = self.config.get('date_flexibility_days', 0)

        departure_dt = datetime.strptime(departure_date, '%Y-%m-%d')

        # Расширяем диапазон дат вылета
        outbound_date_from = (departure_dt - timedelta(days=date_flexibility)).strftime('%Y-%m-%d')
        outbound_date_to = (departure_dt + timedelta(days=date_flexibility)).strftime('%Y-%m-%d')

        # Вычисляем диапазон для дат возврата
        max_nights = max(nights)
        return_date_from = (departure_dt + timedelta(days=1)).strftime('%Y-%m-%d')
        return_date_to = (departure_dt + timedelta(days=max_nights + date_flexibility + 2)).strftime('%Y-%m-%d')

        if date_flexibility > 0:
            print(f"Применена гибкость дат вылета: ±{date_flexibility} {'день' if date_flexibility == 1 else 'дня/дней'}")
            print(f"Диапазон вылета: {outbound_date_from} - {outbound_date_to}")
            print(f"Диапазон возврата: {return_date_from} - {return_date_to}")

        # Шаг 1: Получаем список всех направлений
        print(f"\nПолучение списка направлений из {self.origin}...")
        destinations = self.get_available_destinations(outbound_date_from, outbound_date_to)

        # Фильтруем исключенные аэропорты
        if excluded_airports:
            destinations = {code: info for code, info in destinations.items()
                          if code not in excluded_airports}

        print(f"Найдено {len(destinations)} уникальных направлений")

        if not destinations:
            print("Не найдено доступных направлений")
            return all_results

        # Шаг 2: Получаем ВСЕ рейсы для каждого направления
        print(f"\nПолучение ВСЕХ рейсов туда...")
        outbound_flights_by_dest = {}

        for i, (dest, dest_info) in enumerate(destinations.items(), 1):
            dest_name = dest_info['name']
            print(f"  [{i}/{len(destinations)}] Получение рейсов в {dest_name} ({dest})...")
            flights = self.get_all_flights_to_destination(
                dest,
                dest_name,
                outbound_date_from,
                flex_days_out=date_flexibility * 2  # *2 потому что это +/- от даты
            )
            if flights:
                outbound_flights_by_dest[dest] = flights
                print(f"    Найдено {len(flights)} рейсов")

        total_outbound = sum(len(flights) for flights in outbound_flights_by_dest.values())
        print(f"\nВсего рейсов туда: {total_outbound}")

        # Шаг 3: Получаем ВСЕ обратные рейсы
        print(f"\nПолучение ВСЕХ обратных рейсов...")
        inbound_flights_by_dest = {}

        return_dt_from = datetime.strptime(return_date_from, '%Y-%m-%d')
        return_dt_to = datetime.strptime(return_date_to, '%Y-%m-%d')

        # Вычисляем центр диапазона и flex дни
        days_diff = (return_dt_to - return_dt_from).days
        flex_days_return = days_diff // 2
        return_date_center = return_dt_from + timedelta(days=flex_days_return)
        return_date_center_str = return_date_center.strftime('%Y-%m-%d')

        for i, dest in enumerate(outbound_flights_by_dest.keys(), 1):
            # Получаем название направления из сохраненных рейсов туда
            dest_name = destinations.get(dest, {}).get('name', dest)
            print(f"  [{i}/{len(outbound_flights_by_dest)}] Получение рейсов из {dest_name} ({dest})...")

            # Для обратных рейсов нужно поменять местами origin и destination
            # Получаем рейсы ИЗ dest В self.origin
            params = {
                "ADT": 1,
                "CHD": 0,
                "DateOut": return_date_center_str,
                "Destination": self.origin,  # Валенсия - пункт назначения
                "FlexDaysOut": flex_days_return,
                "INF": 0,
                "Origin": dest,  # dest - пункт отправления
                "RoundTrip": "false",
                "TEEN": 0,
                "ToUs": "AGREED"
            }

            # Проверяем кэш
            cache_key = self._get_cache_key("return_flights", params)
            cached_data = self._get_from_cache(cache_key)
            if cached_data is not None:
                print("    (используется кэш)")
                # Восстанавливаем datetime объекты
                for flight in cached_data:
                    flight['departureTime'] = datetime.fromisoformat(flight['departureTime'])
                    flight['arrivalTime'] = datetime.fromisoformat(flight['arrivalTime'])
                inbound_flights_by_dest[dest] = cached_data
                print(f"    Найдено {len(cached_data)} рейсов")
                continue

            try:
                response = requests.get(self.AVAILABILITY_API, params=params, headers=self._get_random_headers(), timeout=30)
                response.raise_for_status()
                data = response.json()

                flights = []
                for trip in data.get('trips', []):
                    # originName это город вылета (dest), destinationName это Валенсия
                    origin_name = trip.get('originName', dest_name)
                    destination_name = trip.get('destinationName', 'Valencia')

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

                            flight_info = {
                                'origin': segment['origin'],
                                'originName': origin_name,
                                'destination': segment['destination'],
                                'destinationName': destination_name,
                                'departureTime': datetime.fromisoformat(times[0].replace('Z', '+00:00')),
                                'arrivalTime': datetime.fromisoformat(times[1].replace('Z', '+00:00')),
                                'flightNumber': segment['flightNumber'],
                                'price': price,
                                'currency': self.config['currency']
                            }

                            flights.append(flight_info)

                if flights:
                    inbound_flights_by_dest[dest] = flights
                    # Сохраняем в кэш
                    self._save_to_cache(cache_key, flights)
                    print(f"    Найдено {len(flights)} рейсов")
                else:
                    print(f"    Нет обратных рейсов")

            except requests.exceptions.HTTPError as e:
                # 400 ошибка означает что для этого маршрута нет рейсов
                if e.response.status_code == 400:
                    print(f"    Нет обратных рейсов")
                else:
                    print(f"    Ошибка HTTP {e.response.status_code}")
            except Exception as e:
                print(f"    Ошибка: {e}")

        total_inbound = sum(len(flights) for flights in inbound_flights_by_dest.values())
        print(f"\nВсего обратных рейсов: {total_inbound}")

        # Шаг 4: Комбинируем рейсы для каждого количества ночей
        for night_count in nights:
            print(f"\n{'='*60}")
            print(f"Комбинирование рейсов на {night_count} ноч{'ь' if night_count == 1 else 'и/ей'}...")
            print(f"{'='*60}")

            filtered_trips = []
            total_combinations = 0
            rejected_duration = 0
            rejected_price = 0
            rejected_min_hours = 0
            rejected_late_arrival = 0

            # Для каждого направления комбинируем все варианты
            for dest, outbound_list in outbound_flights_by_dest.items():
                inbound_list = inbound_flights_by_dest.get(dest, [])

                if not inbound_list:
                    continue

                # Комбинируем каждый рейс туда с каждым рейсом обратно
                for outbound in outbound_list:
                    for inbound in inbound_list:
                        total_combinations += 1

                        # Фильтр: Проверяем время прилета в пункт назначения (избегаем поздних прилетов)
                        arrival_hour = outbound['arrivalTime'].time().replace(second=0, microsecond=0)
                        max_arrival_time = datetime.strptime(self.config['max_arrival_time_destination'], "%H:%M").time()

                        if arrival_hour > max_arrival_time:
                            rejected_late_arrival += 1
                            continue

                        # Проверяем длительность поездки
                        stay_duration = (inbound['departureTime'] - outbound['arrivalTime']).total_seconds() / 3600

                        # Для 1 ночи требуем минимум часов
                        if night_count == 1:
                            min_hours = self.config['min_hours_for_one_night']
                            if stay_duration < min_hours:
                                rejected_min_hours += 1
                                continue

                        # Проверяем что длительность соответствует ночам (±12 часов)
                        days_diff = stay_duration / 24
                        if abs(days_diff - night_count) > 0.5:
                            rejected_duration += 1
                            continue

                        # Проверяем общую цену
                        total_price = outbound['price'] + inbound['price']
                        if total_price > self.config['max_price']:
                            rejected_price += 1
                            continue

                        # Создаем комбинацию
                        trip_dict = {
                            'totalPrice': total_price,
                            'outbound': outbound,
                            'inbound': inbound,
                            'nights': night_count,
                            'stay_duration_hours': round(stay_duration, 1),
                            'destination_full': f"{dest}"  # Можно добавить полное название
                        }

                        filtered_trips.append(trip_dict)

            print(f"Проверено комбинаций: {total_combinations}")
            print(f"Отклонено по позднему прилету: {rejected_late_arrival}")
            print(f"Отклонено по длительности: {rejected_duration}")
            print(f"Отклонено по мин. часам (1 ночь): {rejected_min_hours}")
            print(f"Отклонено по цене: {rejected_price}")
            print(f"Подходящих вариантов: {len(filtered_trips)}")

            # Сортируем по цене
            filtered_trips.sort(key=lambda x: x['totalPrice'])

            # Ограничиваем количество результатов
            max_results = self.config['max_results']
            limited_trips = filtered_trips[:max_results]

            all_results.extend(limited_trips)

            # Выводим результаты
            self.print_results(limited_trips, night_count)

        return all_results

    def search_one_day_trips(
        self,
        excluded_airports_override: List[str] = None
    ) -> List[Dict]:
        """
        Поиск однодневных поездок с ночевкой: вылет утром, возврат вечером на следующий день.
        Ищет варианты на 2 месяца вперед (60 дней).
        Не использует FlexDaysOut - итерируется по датам вручную.
        Задержка 100 миллисекунд между запросами с ротацией User-Agent.

        Args:
            excluded_airports_override: список кодов исключенных аэропортов

        Returns:
            Список подходящих рейсов
        """
        all_results = []

        # Объединяем исключенные аэропорты из конфига и командной строки
        excluded_airports = set(self.config.get('excluded_airports', []))
        if excluded_airports_override:
            excluded_airports.update(excluded_airports_override)

        # Определяем диапазон поиска: завтра + 2 месяца (60 дней)
        today = datetime.now().date()
        start_date = today + timedelta(days=1)  # Начинаем с завтра
        end_date = today + timedelta(days=60)  # 2 месяца вперед

        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')

        print(f"\nПоиск с {start_date_str} по {end_date_str}")

        # Шаг 1: Получаем список всех направлений
        print(f"\nПолучение списка направлений из {self.origin}...")
        destinations = self.get_available_destinations(start_date_str, end_date_str)

        # Фильтруем исключенные аэропорты
        if excluded_airports:
            destinations = {code: info for code, info in destinations.items()
                          if code not in excluded_airports}

        print(f"Найдено {len(destinations)} уникальных направлений")

        if not destinations:
            print("Не найдено доступных направлений")
            return all_results

        # Шаг 2: Итерируемся по датам и направлениям
        print(f"\nПоиск однодневных вариантов по датам...")

        # Для каждого направления собираем все утренние рейсы сразу
        for i, (dest, dest_info) in enumerate(destinations.items(), 1):
            dest_name = dest_info['name']
            print(f"  [{i}/{len(destinations)}] Проверка {dest_name} ({dest})...")

            morning_flights_all = []

            # Итерируемся по датам вместо использования FlexDaysOut
            current_date = start_date
            while current_date <= end_date:
                date_str = current_date.strftime('%Y-%m-%d')

                try:
                    # Получаем рейсы на конкретную дату (без flex)
                    flights = self.get_all_flights_to_destination(
                        dest,
                        dest_name,
                        date_str,
                        flex_days_out=0  # Без гибкости - конкретная дата
                    )

                    # Фильтруем только утренние вылеты (до 12:00)
                    morning_flights = [f for f in flights
                                     if f['departureTime'].time().hour < 12]

                    morning_flights_all.extend(morning_flights)

                    # Задержка 100 миллисекунд между запросами
                    time.sleep(0.1)

                except Exception:
                    # Нет рейсов на эту дату - продолжаем
                    pass

                current_date += timedelta(days=1)

            if not morning_flights_all:
                continue

            print(f"    Найдено {len(morning_flights_all)} утренних рейсов")

            # Для каждого утреннего вылета ищем вечерний возврат
            for outbound in morning_flights_all:
                outbound_date = outbound['departureTime'].date()

                # Ищем возвраты на тот же день и следующий
                return_dates = [outbound_date, outbound_date + timedelta(days=1)]

                for return_date in return_dates:
                    return_date_str = return_date.strftime('%Y-%m-%d')

                    # Получаем обратные рейсы на конкретную дату
                    params = {
                        "ADT": 1,
                        "CHD": 0,
                        "DateOut": return_date_str,
                        "Destination": self.origin,
                        "FlexDaysOut": 0,  # Без гибкости
                        "INF": 0,
                        "Origin": dest,
                        "RoundTrip": "false",
                        "TEEN": 0,
                        "ToUs": "AGREED"
                    }

                    cache_key = self._get_cache_key("one_day_return", params)
                    cached_data = self._get_from_cache(cache_key)

                    if cached_data is not None:
                        inbound_flights = cached_data
                        # Восстанавливаем datetime объекты
                        for flight in inbound_flights:
                            flight['departureTime'] = datetime.fromisoformat(flight['departureTime'])
                            flight['arrivalTime'] = datetime.fromisoformat(flight['arrivalTime'])
                    else:
                        try:
                            response = requests.get(self.AVAILABILITY_API, params=params, headers=self._get_random_headers(), timeout=30)
                            response.raise_for_status()
                            data = response.json()

                            inbound_flights = []
                            for trip in data.get('trips', []):
                                origin_name = trip.get('originName', dest_name)
                                destination_name = trip.get('destinationName', 'Valencia')

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

                                        flight_info = {
                                            'origin': segment['origin'],
                                            'originName': origin_name,
                                            'destination': segment['destination'],
                                            'destinationName': destination_name,
                                            'departureTime': datetime.fromisoformat(times[0].replace('Z', '+00:00')),
                                            'arrivalTime': datetime.fromisoformat(times[1].replace('Z', '+00:00')),
                                            'flightNumber': segment['flightNumber'],
                                            'price': price,
                                            'currency': self.config['currency']
                                        }

                                        inbound_flights.append(flight_info)

                            # Сохраняем в кэш
                            self._save_to_cache(cache_key, inbound_flights)

                            # Задержка 1 секунда между запросами
                            time.sleep(1)

                        except Exception:
                            continue

                    # Фильтруем вечерние прилеты (после 18:00)
                    evening_returns = [f for f in inbound_flights
                                     if f['arrivalTime'].time().hour >= 18]

                    # Комбинируем и фильтруем
                    for inbound in evening_returns:
                        # ТОЛЬКО варианты с ночевкой (вылет и прилет обратно в разные дни)
                        if outbound['departureTime'].date() == inbound['arrivalTime'].date():
                            continue

                        # Вычисляем длительность пребывания
                        stay_duration = (inbound['departureTime'] - outbound['arrivalTime']).total_seconds() / 3600

                        # Минимум 6 часов, максимум 36 часов (1.5 дня)
                        if stay_duration < 6 or stay_duration > 36:
                            continue

                        # Проверяем общую цену
                        total_price = outbound['price'] + inbound['price']
                        if total_price > self.config['max_price']:
                            continue

                        # Создаем комбинацию
                        trip_dict = {
                            'totalPrice': total_price,
                            'outbound': outbound,
                            'inbound': inbound,
                            'nights': 1,  # Всегда 1 ночь
                            'stay_duration_hours': round(stay_duration, 1),
                            'destination_full': dest
                        }

                        all_results.append(trip_dict)

            if all_results:
                print(f"    Найдено {len([r for r in all_results if r['destination_full'] == dest])} вариантов")

        # Сортируем по цене
        all_results.sort(key=lambda x: x['totalPrice'])

        # Ограничиваем количество результатов
        max_results = self.config['max_results']
        limited_results = all_results[:max_results]

        # Выводим результаты
        self.print_one_day_results(limited_results)

        return limited_results

    def print_one_day_results(self, trips: List[Dict]):
        """
        Вывод результатов однодневных поездок.

        Args:
            trips: список рейсов
        """
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
            is_same_day = out_dep.date() == in_arr.date()

            same_day_label = " (в тот же день)" if is_same_day else " (с ночевкой)"

            print(f"{i}. {destination_name} ({destination_code}) - {price} {self.config['currency']}{same_day_label}")
            print(f"   Туда:    {out_dep.strftime('%d.%m.%Y %H:%M')} → {out_arr.strftime('%H:%M')}")
            print(f"   Обратно: {in_dep.strftime('%d.%m.%Y %H:%M')} → {in_arr.strftime('%H:%M')}")
            print(f"   Время в городе: {stay_hours} часов")
            print(f"   Рейсы: {outbound['flightNumber']} / {inbound['flightNumber']}")
            print()

    def print_results(self, trips: List[Dict], nights: int):
        """
        Вывод результатов поиска в консоль.

        Args:
            trips: список рейсов
            nights: количество ночей
        """
        if not trips:
            print(f"Не найдено подходящих рейсов на {nights} ноч{'ь' if nights == 1 else 'и/ей'}.")
            return

        print(f"\nНайдено {len(trips)} рейс(ов) на {nights} ноч{'ь' if nights == 1 else 'и/ей'}:\n")

        for i, trip in enumerate(trips, 1):
            outbound = trip['outbound']
            inbound = trip['inbound']

            out_dep = outbound['departureTime']
            out_arr = outbound['arrivalTime']
            in_dep = inbound['departureTime']
            in_arr = inbound['arrivalTime']

            # Используем полное название если доступно, иначе код аэропорта
            destination_name = outbound.get('destinationName', outbound['destination'])
            destination_code = outbound['destination']

            # Для обратных рейсов тоже выводим полные названия
            origin_name_out = outbound.get('originName', outbound['origin'])
            origin_name_in = inbound.get('originName', inbound['origin'])

            price = trip['totalPrice']
            stay_hours = trip.get('stay_duration_hours', 0)

            print(f"{i}. {destination_name} ({destination_code}) - {price} {self.config['currency']}")
            print(f"   Туда:    {out_dep.strftime('%d.%m.%Y %H:%M')} → {out_arr.strftime('%H:%M')}")
            print(f"   Обратно: {in_dep.strftime('%d.%m.%Y %H:%M')} → {in_arr.strftime('%H:%M')}")
            print(f"   Длительность:  {stay_hours} часов ({stay_hours/24:.1f} дней)")
            print(f"   Рейсы: {outbound['flightNumber']} / {inbound['flightNumber']}")
            print()
