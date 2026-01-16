#!/usr/bin/env python3
"""Проверка рейсов по дням"""
from datetime import datetime, timedelta, date
from ryanair import Ryanair

api = Ryanair(currency="EUR")

# Пробуем 3-дневный диапазон
start_date = date(2026, 5, 17)
end_date = date(2026, 5, 19)

try:
    print(f"Получаем рейсы VLC на {start_date} - {end_date}...")
    flights = api.get_cheapest_flights("VLC", start_date, end_date)

    # Группируем по направлению и дате
    by_dest_date = {}
    for f in flights:
        key = (f.destination, f.departureTime.date())
        if key not in by_dest_date:
            by_dest_date[key] = []
        by_dest_date[key].append(f)

    print(f"\nВсего рейсов: {len(flights)}")

    # Проверим есть ли направления с несколькими рейсами
    multi_flight_dests = []
    for (dest, date_val), dest_flights in by_dest_date.items():
        if len(dest_flights) > 1:
            multi_flight_dests.append((dest, date_val, dest_flights))

    if multi_flight_dests:
        print(f"\nНаправления с несколькими рейсами в один день:")
        for dest, date_val, dest_flights in multi_flight_dests:
            print(f"  {dest} на {date_val}: {len(dest_flights)} рейсов")
            for f in dest_flights:
                print(f"    {f.departureTime.strftime('%H:%M')} - {f.price} EUR")
    else:
        print("\nНет направлений с несколькими рейсами в один день")
        print("API возвращает только 1 самый дешевый рейс на направление в день")

    # Покажем сколько рейсов по дням
    by_date = {}
    for f in flights:
        d = f.departureTime.date()
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(f)

    print(f"\nРейсы по дням:")
    for d in sorted(by_date.keys()):
        print(f"  {d}: {len(by_date[d])} направлений")

except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
