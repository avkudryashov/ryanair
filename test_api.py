#!/usr/bin/env python3
"""Тестовый скрипт для проверки структуры данных API"""
from datetime import datetime, timedelta, date
from ryanair import Ryanair

api = Ryanair(currency="EUR")

# Пробуем получить рейсы
tomorrow = datetime.today().date() + timedelta(days=1)
tomorrow_2 = tomorrow + timedelta(days=2)

try:
    trips = api.get_cheapest_return_flights("VLC", tomorrow, tomorrow, tomorrow_2, tomorrow_2)

    if trips:
        print(f"Найдено {len(trips)} рейсов")
        trip = trips[0]
        print(f"\nСтруктура Trip:")
        print(f"  Тип: {type(trip)}")
        print(f"  Атрибуты: {dir(trip)}")
        print(f"  Значения: {trip}")

        print(f"\nСтруктура outbound Flight:")
        outbound = trip.outbound
        print(f"  Тип: {type(outbound)}")
        print(f"  Атрибуты: {[attr for attr in dir(outbound) if not attr.startswith('_')]}")
        print(f"  Значения: {outbound}")

    else:
        print("Рейсов не найдено")
except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
