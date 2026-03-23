#!/usr/bin/env python3
"""Flask веб-интерфейс для поиска дешевых рейсов Ryanair."""
import threading
import time
from datetime import date, timedelta
from flask import Flask, render_template, request, jsonify
from flight_search import FlightSearcher

app = Flask(__name__)
searcher = FlightSearcher()

# Загружаем список аэропортов при старте (из кэша если есть)
airports = searcher.get_airports()

# Собираем уникальные страны из аэропортов и маппинг страна→аэропорты
countries = sorted({ap['country'] for ap in airports if ap['country']})
country_to_airports = {}
for ap in airports:
    country_to_airports.setdefault(ap['country'], []).append(ap['code'])

# Координаты аэропортов для геолокации (code → {lat, lng})
airport_coords = {ap['code']: {'lat': ap.get('lat', 0), 'lng': ap.get('lng', 0)} for ap in airports}


# ── Background cache warming ─────────────────────────────
_warmed_origins = set()


def warm_origin(origin_code: str):
    """Прогревает кэш направлений для указанного аэропорта."""
    if origin_code in _warmed_origins:
        return
    _warmed_origins.add(origin_code)

    def _do_warm():
        try:
            original = searcher.origin
            searcher.origin = origin_code
            today = date.today()
            date_from = today.isoformat()
            date_to = (today + timedelta(days=14)).isoformat()
            searcher.get_available_destinations(date_from, date_to)
            print(f"[warming] Направления из {origin_code} на {date_from}..{date_to} прогреты")
        except Exception as e:
            print(f"[warming] Ошибка {origin_code}: {e}")
        finally:
            searcher.origin = original

    threading.Thread(target=_do_warm, daemon=True).start()


def warm_cache_loop():
    """Периодический прогрев кэша для всех известных origins."""
    # Прогреваем config origin сразу
    warm_origin(searcher.config['origin_airport'])
    while True:
        time.sleep(900)  # каждые 15 минут
        for origin in list(_warmed_origins):
            try:
                original = searcher.origin
                searcher.origin = origin
                today = date.today()
                date_from = today.isoformat()
                date_to = (today + timedelta(days=14)).isoformat()
                searcher.get_available_destinations(date_from, date_to)
            except Exception:
                pass
            finally:
                searcher.origin = original


threading.Thread(target=warm_cache_loop, daemon=True).start()


def serialize_trip(trip):
    """Конвертирует trip dict в плоский словарь для шаблона."""
    out = trip['outbound']
    inb = trip['inbound']
    return {
        'destination': out.get('destinationName', out['destination']),
        'dest_code': out['destination'],
        'total_price': round(trip['totalPrice'], 2),
        'currency': out['currency'],
        'nights': trip['nights'],
        'stay_hours': trip.get('stay_duration_hours', 0),
        'out_date': out['departureTime'].strftime('%d.%m.%Y'),
        'out_dep': out['departureTime'].strftime('%H:%M'),
        'out_arr': out['arrivalTime'].strftime('%H:%M'),
        'out_flight': out['flightNumber'],
        'in_date': inb['departureTime'].strftime('%d.%m.%Y'),
        'in_dep': inb['departureTime'].strftime('%H:%M'),
        'in_arr': inb['arrivalTime'].strftime('%H:%M'),
        'in_flight': inb['flightNumber'],
    }


@app.route('/api/warm', methods=['POST'])
def api_warm():
    """Запускает прогрев кэша для указанного аэропорта."""
    origin = request.json.get('origin', '').strip().upper()
    if not origin or len(origin) != 3:
        return jsonify({'error': 'invalid origin'}), 400
    warm_origin(origin)
    return jsonify({'status': 'warming', 'origin': origin})


@app.route('/')
def index():
    mode = request.args.get('mode')
    origin = request.args.get('origin', '').strip().upper() or None

    # Исключённые страны (из dropdown)
    excl_countries_str = request.args.get('excl_countries', '').strip()
    excluded_countries = [c.strip() for c in excl_countries_str.split(',') if c.strip()] if excl_countries_str else []

    # Исключённые аэропорты (из dropdown)
    excl_airports_str = request.args.get('excl_airports', '').strip()
    excluded_airports = [c.strip().upper() for c in excl_airports_str.split(',') if c.strip()] if excl_airports_str else []

    max_price = int(request.args.get('max_price', '') or str(searcher.config['max_price']))
    error = None
    results = []
    freshness = None

    if mode == 'regular':
        departure_date = request.args.get('departure_date', '').strip()
        nights_str = request.args.get('nights', '').strip()
        flex_days = int(request.args.get('flex_days', '1') or '1')

        if not departure_date or not nights_str:
            error = "Укажите дату вылета и количество ночей"
        else:
            try:
                nights = [int(n.strip()) for n in nights_str.split(',')]
                # Прогреваем кэш для выбранного origin
                if origin:
                    warm_origin(origin)
                trips = searcher.search_flights(
                    departure_date, nights,
                    excluded_airports_override=excluded_airports or None,
                    excluded_countries_override=excluded_countries or None,
                    origin_override=origin,
                    flex_days_override=flex_days,
                    max_price_override=max_price,
                )
                results = [serialize_trip(t) for t in trips]
                freshness = searcher.get_data_freshness()
            except ValueError:
                error = "Неверный формат данных. Дата: YYYY-MM-DD, ночи: 1,2,3"
            except Exception as e:
                error = f"Ошибка поиска: {e}"

    template_data = dict(
        results=results, error=error, searched=(mode == 'regular'),
        args=request.args, airports=airports,
        countries=countries,
        country_to_airports=country_to_airports,
        airport_coords=airport_coords,
        today=date.today().isoformat(),
        max_price=searcher.config['max_price'],
        freshness=freshness,
    )

    # HTMX partial response — return only results fragment
    if request.headers.get('HX-Request'):
        return render_template('partials/results.html', **template_data)

    return render_template('index.html', **template_data)


if __name__ == '__main__':
    app.run(debug=True, port=5000)
