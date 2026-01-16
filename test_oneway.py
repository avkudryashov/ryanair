#!/usr/bin/env python3
"""Тестовый скрипт для проверки односторонних рейсов"""
from datetime import datetime, timedelta, date
from ryanair import Ryanair

api = Ryanair(currency="EUR")

# Пробуем получить односторонние рейсы
tomorrow = datetime.today().date() + timedelta(days=1)
tomorrow_1 = tomorrow + timedelta(days=1)

try:
    print("Получаем односторонние рейсы из VLC...")
    flights = api.get_cheapest_flights("VLC", tomorrow, tomorrow_1)

    if flights:
        print(f"Найдено {len(flights)} рейсов")
        flight = flights[0]
        print(f"\nСтруктура Flight:")
        print(f"  Тип: {type(flight)}")
        print(f"  Значения: {flight}")

        # Проверяем есть ли метод получения рейсов в конкретный аэропорт
        print("\n" + "="*60)
        print("Получаем рейсы из BCN обратно в VLC...")
        return_flights = api.get_cheapest_flights("BCN", tomorrow_1, tomorrow_1 + timedelta(days=1), destination_airport="VLC")

        if return_flights:
            print(f"Найдено {len(return_flights)} обратных рейсов")
            print(f"Пример: {return_flights[0]}")
    else:
        print("Рейсов не найдено")
except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
