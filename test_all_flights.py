#!/usr/bin/env python3
"""Тестовый скрипт для проверки всех доступных рейсов"""
from datetime import datetime, timedelta, date
from ryanair import Ryanair

api = Ryanair(currency="EUR")

# Пробуем получить рейсы в Барселону
test_date = date(2026, 5, 18)

try:
    print("Получаем рейсы VLC -> BCN на 18 мая 2026...")
    flights = api.get_cheapest_flights("VLC", test_date, test_date)

    # Фильтруем только Барселону
    bcn_flights = [f for f in flights if f.destination == "BCN"]

    print(f"Найдено {len(bcn_flights)} рейсов в BCN:")
    for flight in bcn_flights:
        print(f"  {flight.departureTime.strftime('%H:%M')} - {flight.price} EUR ({flight.flightNumber})")

    # Проверим другое направление
    print("\nРейсы в другие популярные направления:")
    destinations = {}
    for f in flights:
        dest = f.destination
        if dest not in destinations:
            destinations[dest] = []
        destinations[dest].append(f)

    # Покажем сколько рейсов в каждое направление
    for dest, dest_flights in sorted(destinations.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
        print(f"  {dest}: {len(dest_flights)} рейсов, цены: {[f.price for f in dest_flights]}")

except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
