#!/usr/bin/env python3
"""Тестовый скрипт для проверки структуры данных Flyan API"""
from datetime import datetime, timedelta
from flyan import RyanAir, FlightSearchParams

client = RyanAir(currency="EUR")

# Пробуем получить рейсы туда-обратно
try:
    search_params = FlightSearchParams(
        from_airport="VLC",
        to_airport="BCN",  # Барселона близко, должны быть рейсы
        from_date=datetime(2026, 5, 18),
        to_date=datetime(2026, 5, 19),
        max_price=200
    )

    print("Поиск рейсов туда...")
    outbound_flights = client.get_oneways(search_params)

    if outbound_flights:
        print(f"Найдено {len(outbound_flights)} рейсов туда")
        flight = outbound_flights[0]
        print(f"\nСтруктура Flight:")
        print(f"  Тип: {type(flight)}")
        print(f"  Атрибуты: {[attr for attr in dir(flight) if not attr.startswith('_')]}")
        print(f"\n  Значение: {flight}")

        # Проверим что внутри
        if hasattr(flight, 'dict'):
            print(f"\n  Dict: {flight.dict()}")
        elif hasattr(flight, 'model_dump'):
            print(f"\n  Model Dump: {flight.model_dump()}")
    else:
        print("Рейсов туда не найдено")

    # Теперь попробуем get_return_flights
    print("\n" + "="*60)
    print("Поиск рейсов туда-обратно...")
    return_flights = client.get_return_flights(search_params)

    if return_flights:
        print(f"Найдено {len(return_flights)} комбинаций туда-обратно")
        flight_pair = return_flights[0]
        print(f"\nСтруктура ReturnFlight:")
        print(f"  Тип: {type(flight_pair)}")
        print(f"  Атрибуты: {[attr for attr in dir(flight_pair) if not attr.startswith('_')]}")
        if hasattr(flight_pair, 'model_dump'):
            print(f"\n  Model Dump: {flight_pair.model_dump()}")
    else:
        print("Рейсов туда-обратно не найдено")

except Exception as e:
    print(f"Ошибка: {e}")
    import traceback
    traceback.print_exc()
