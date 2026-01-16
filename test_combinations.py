#!/usr/bin/env python3
"""Проверка комбинаций рейсов"""
from datetime import datetime, timedelta, date
from ryanair import Ryanair

api = Ryanair(currency="EUR")

# Берем Марракеш как пример
outbound_date = date(2026, 5, 17)
outbound_date_end = date(2026, 5, 19)

try:
    print("Получаем рейсы VLC -> RAK...")
    outbound_flights = api.get_cheapest_flights("VLC", outbound_date, outbound_date_end)
    rak_outbound = [f for f in outbound_flights if f.destination == "RAK"]

    print(f"Найдено {len(rak_outbound)} рейсов VLC -> RAK:")
    for f in rak_outbound:
        print(f"  {f.departureTime.strftime('%Y-%m-%d %H:%M')} - {f.price} EUR")

    print("\nПолучаем рейсы RAK -> VLC...")
    return_date = date(2026, 5, 19)
    return_date_end = date(2026, 5, 23)

    inbound_flights = api.get_cheapest_flights("RAK", return_date, return_date_end, destination_airport="VLC")

    print(f"Найдено {len(inbound_flights)} рейсов RAK -> VLC:")
    for f in inbound_flights:
        print(f"  {f.departureTime.strftime('%Y-%m-%d %H:%M')} - {f.price} EUR")

    # Комбинируем
    print(f"\nВсего возможных комбинаций: {len(rak_outbound) * len(inbound_flights)}")
    for out in rak_outbound:
        for ret in inbound_flights:
            total = out.price + ret.price
            duration = (ret.departureTime - out.departureTime).total_seconds() / 3600
            print(f"  {out.departureTime.strftime('%d.%m')} -> {ret.departureTime.strftime('%d.%m')}: {total} EUR ({duration:.1f}ч)")

except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
