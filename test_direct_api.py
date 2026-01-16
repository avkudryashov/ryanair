#!/usr/bin/env python3
"""Тестирование прямых запросов к API Ryanair"""
import requests
import json
from datetime import date

# Попробуем availability API
base_url = "https://www.ryanair.com/api/booking/v4/availability"

params = {
    "ADT": 1,  # Взрослых
    "CHD": 0,  # Детей
    "DateIn": "2026-05-20",  # Дата обратно
    "DateOut": "2026-05-18",  # Дата туда
    "Destination": "RAK",  # Марракеш
    "FlexDaysIn": 0,
    "FlexDaysOut": 0,
    "INF": 0,  # Младенцев
    "Origin": "VLC",  # Валенсия
    "RoundTrip": "true",
    "TEEN": 0,
    "ToUs": "AGREED"
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
}

try:
    print("Попытка 1: Availability API (v4)")
    print(f"URL: {base_url}")
    print(f"Параметры: {params}")

    response = requests.get(base_url, params=params, headers=headers, timeout=10)
    print(f"Статус: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"Успех! Получено данных: {len(str(data))} символов")

        # Смотрим структуру
        if 'trips' in data:
            print(f"\nНайдено trips: {len(data['trips'])}")
            if data['trips']:
                trip = data['trips'][0]
                print(f"Структура trip: {list(trip.keys())}")
                if 'dates' in trip:
                    print(f"Dates в trip: {len(trip['dates'])}")
                    if trip['dates']:
                        day = trip['dates'][0]
                        print(f"Структура date: {list(day.keys())}")
                        if 'flights' in day:
                            print(f"Flights в date: {len(day['flights'])}")
                            if day['flights']:
                                flight = day['flights'][0]
                                print(f"\nПример рейса:")
                                print(json.dumps(flight, indent=2, ensure_ascii=False)[:500])

        # Сохраним для анализа
        with open('availability_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("\nПолный ответ сохранен в availability_response.json")

    else:
        print(f"Ошибка: {response.text[:500]}")

except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Попытка 2: Fare Finder API (oneWayFares)")

farfnd_url = "https://services-api.ryanair.com/farfnd/v4/oneWayFares"
farfnd_params = {
    "departureAirportIataCode": "VLC",
    "outboundDepartureDateFrom": "2026-05-18",
    "outboundDepartureDateTo": "2026-05-19",
    "currency": "EUR"
}

try:
    response = requests.get(farfnd_url, params=farfnd_params, headers=headers, timeout=10)
    print(f"Статус: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"Успех! Найдено fares: {len(data.get('fares', []))}")

        with open('farfnd_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Полный ответ сохранен в farfnd_response.json")

    else:
        print(f"Ошибка: {response.text[:500]}")

except Exception as e:
    print(f"Ошибка: {e}")
