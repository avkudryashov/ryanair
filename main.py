#!/usr/bin/env python3
"""
Основной скрипт для поиска дешевых рейсов из Валенсии.

Использование:
    python main.py --departure-date 2024-02-15 --nights 1,2,3
    python main.py -d 2024-02-15 -n 2
"""
import argparse
import sys
from datetime import datetime
from flight_search import FlightSearcher


def parse_nights(nights_str: str) -> list:
    """
    Парсинг строки с количеством ночей в список.

    Args:
        nights_str: строка вида "1,2,3" или "2"

    Returns:
        Список целых чисел
    """
    try:
        return [int(n.strip()) for n in nights_str.split(',')]
    except ValueError:
        print(f"Ошибка: неверный формат для количества ночей: {nights_str}")
        print("Используйте формат: 1 или 1,2,3")
        sys.exit(1)


def validate_date(date_str: str) -> str:
    """
    Проверка корректности формата даты.

    Args:
        date_str: строка с датой

    Returns:
        Проверенная строка с датой
    """
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except ValueError:
        print(f"Ошибка: неверный формат даты: {date_str}")
        print("Используйте формат YYYY-MM-DD, например: 2024-02-15")
        sys.exit(1)


def main():
    """Основная функция программы."""
    parser = argparse.ArgumentParser(
        description='Поиск дешевых рейсов из Валенсии',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s -d 2024-02-15 -n 1,2,3
  %(prog)s --departure-date 2024-05-18 --nights 2
  %(prog)s -d 2024-04-01 -n 1 --config custom_config.yaml

Примечания:
  - Дата вылета будет расширена на ±N дней (по умолчанию ±1 день) из config.yaml
  - Поздние прилеты в пункт назначения фильтруются (настраивается в config.yaml)
  - Для поездок на 1 ночь требуется минимум 18 часов пребывания
  - В Валенсию можно прилетать в любое время
  - Результаты сортируются по цене
        """
    )

    parser.add_argument(
        '-d', '--departure-date',
        type=str,
        required=False,
        help='Дата вылета из Валенсии (YYYY-MM-DD), например: 2024-02-15'
    )

    parser.add_argument(
        '-n', '--nights',
        type=str,
        required=False,
        help='Количество ночей (можно указать несколько через запятую), например: 1,2,3'
    )

    parser.add_argument(
        '--one-day',
        action='store_true',
        help='Режим однодневных поездок с ночевкой: вылет утром, возврат вечером на следующий день. Ищет на 2 месяца вперед'
    )

    parser.add_argument(
        '-c', '--config',
        type=str,
        default='config.yaml',
        help='Путь к файлу конфигурации (по умолчанию: config.yaml)'
    )

    parser.add_argument(
        '-e', '--exclude',
        type=str,
        default='',
        help='Исключить аэропорты (коды через запятую), например: IBZ,PMI'
    )

    args = parser.parse_args()

    # Парсинг исключенных аэропортов
    excluded_airports = []
    if args.exclude:
        excluded_airports = [code.strip().upper() for code in args.exclude.split(',')]

    print("="*60)
    print("🔍 ПОИСК ДЕШЕВЫХ РЕЙСОВ ИЗ ВАЛЕНСИИ")
    print("="*60)

    try:
        searcher = FlightSearcher(config_path=args.config)

        # Режим однодневных поездок
        if args.one_day:
            print("Режим: Однодневные поездки с ночевкой")
            print("Поиск: 2 месяца вперед (вылет утром, возврат вечером на следующий день)")
            if excluded_airports:
                print(f"Исключены аэропорты: {', '.join(excluded_airports)}")
            print("="*60)

            results = searcher.search_one_day_trips(
                excluded_airports_override=excluded_airports
            )
        else:
            # Обычный режим
            if not args.departure_date or not args.nights:
                print("Ошибка: требуются параметры -d и -n, или используйте --one-day")
                sys.exit(1)

            # Валидация аргументов
            departure_date = validate_date(args.departure_date)
            nights = parse_nights(args.nights)

            # Проверка количества ночей
            if any(n < 1 for n in nights):
                print("Ошибка: количество ночей должно быть больше 0")
                sys.exit(1)

            print(f"Дата вылета: {departure_date}")
            print(f"Количество ночей: {', '.join(map(str, nights))}")
            if excluded_airports:
                print(f"Исключены аэропорты: {', '.join(excluded_airports)}")
            print("="*60)

            results = searcher.search_flights(
                departure_date=departure_date,
                nights=nights,
                excluded_airports_override=excluded_airports
            )

        print("\n" + "="*60)
        print(f"Всего найдено: {len(results)} подходящих вариантов")
        print("="*60)

    except FileNotFoundError:
        print(f"Ошибка: файл конфигурации '{args.config}' не найден")
        sys.exit(1)
    except Exception as e:
        print(f"Произошла ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
