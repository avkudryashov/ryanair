#!/usr/bin/env python3
"""Flask веб-интерфейс для поиска дешевых рейсов Ryanair."""
import threading
import time
from datetime import date, timedelta
from flask import Flask, render_template, request, jsonify
from flight_search import FlightSearcher
from translations import (
    get_translator, detect_locale, SUPPORTED_LOCALES, OG_LOCALES, TRANSLATIONS,
)

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


@app.route('/api/destinations')
def api_destinations():
    """Возвращает список доступных направлений из аэропорта."""
    origin = request.args.get('origin', '').strip().upper()
    departure_date = request.args.get('date', '').strip()
    flex_days = int(request.args.get('flex', '1') or '1')

    if not origin or not departure_date:
        return jsonify({'error': 'origin and date required'}), 400

    warm_origin(origin)
    try:
        dt = date.fromisoformat(departure_date)
        date_from = (dt - timedelta(days=flex_days)).isoformat()
        date_to = (dt + timedelta(days=flex_days)).isoformat()

        original_origin = searcher.origin
        searcher.origin = origin
        try:
            dests = searcher.get_available_destinations(date_from, date_to)
        finally:
            searcher.origin = original_origin

        # dests is {code: {name, country, price, ...}}
        result = [
            {'code': code, 'name': info['name'], 'country': info.get('country', ''), 'min_price': info.get('price', 0)}
            for code, info in sorted(dests.items(), key=lambda x: x[1].get('price', 999))
        ]
        return jsonify({'origin': origin, 'destinations': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
        destination = request.args.get('destination', '').strip().upper() or None

        lang = detect_locale(request)
        _ = get_translator(lang)

        if not departure_date or not nights_str:
            error = _('error_missing_fields')
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
                    destination_override=destination,
                )
                results = [serialize_trip(t) for t in trips]
                freshness = searcher.get_data_freshness()
            except ValueError:
                error = _('error_bad_format')
            except Exception as e:
                error = _('error_search', e=e)

    lang = detect_locale(request)
    _ = get_translator(lang)

    # Resolve origin code & name for flow diagram display
    origin_code = origin or searcher.config.get('origin_airport', 'VLC')
    origin_name = origin_code
    for ap in airports:
        if ap['code'] == origin_code:
            origin_name = ap['name']
            break

    template_data = dict(
        results=results, error=error, searched=(mode == 'regular'),
        args=request.args, airports=airports,
        countries=countries,
        country_to_airports=country_to_airports,
        airport_coords=airport_coords,
        today=date.today().isoformat(),
        max_price=searcher.config['max_price'],
        freshness=freshness,
        origin_code=origin_code, origin_name=origin_name,
        _=_, lang=lang,
        supported_locales=SUPPORTED_LOCALES,
        og_locale=OG_LOCALES.get(lang, 'en_US'),
    )

    # HTMX partial response — return only results fragment
    if request.headers.get('HX-Request'):
        return render_template('partials/results.html', **template_data)

    return render_template('index.html', **template_data)


@app.route('/api/nomad/options')
def api_nomad_options():
    """Возвращает top-N дешёвых one-way рейсов из аэропорта."""
    origin = request.args.get('origin', '').strip().upper()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    max_leg_price = int(request.args.get('max_leg_price', '50') or '50')
    top_n = int(request.args.get('top_n', '10') or '10')

    excl_airports_str = request.args.get('excl_airports', '').strip()
    excl_airports = [a.strip().upper() for a in excl_airports_str.split(',') if a.strip()] if excl_airports_str else []

    excl_countries_str = request.args.get('excl_countries', '').strip()
    excl_countries = [c.strip() for c in excl_countries_str.split(',') if c.strip()] if excl_countries_str else []

    if not origin or not date_from or not date_to:
        return jsonify({'error': 'origin, date_from, date_to required'}), 400

    warm_origin(origin)
    try:
        options = searcher.search_nomad_options(
            origin=origin, date_from=date_from, date_to=date_to,
            max_price_per_leg=max_leg_price, top_n=top_n,
            excluded_airports=excl_airports or None,
            excluded_countries=excl_countries or None,
        )
        return jsonify({'origin': origin, 'options': options})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/nomad/routes')
def api_nomad_routes():
    """Автоматический поиск nomad-маршрутов с возвратом."""
    origin = request.args.get('origin', '').strip().upper()
    departure_date = request.args.get('departure_date', '').strip()
    hops = int(request.args.get('hops', '2') or '2')
    nights_str = request.args.get('nights', '1,2,3').strip()
    max_leg_price = int(request.args.get('max_price', '50') or '50')
    top_n = int(request.args.get('top_n', '10') or '10')

    excl_airports_str = request.args.get('excl_airports', '').strip()
    excl_airports = [a.strip().upper() for a in excl_airports_str.split(',') if a.strip()] if excl_airports_str else []

    excl_countries_str = request.args.get('excl_countries', '').strip()
    excl_countries = [c.strip() for c in excl_countries_str.split(',') if c.strip()] if excl_countries_str else []

    if not origin or not departure_date:
        return jsonify({'error': 'origin and departure_date required'}), 400

    try:
        nights = [int(n.strip()) for n in nights_str.split(',') if n.strip()]
        if not nights:
            nights = [1, 2, 3]
    except ValueError:
        nights = [1, 2, 3]

    warm_origin(origin)
    try:
        routes = searcher.search_nomad_routes(
            origin=origin, departure_date=departure_date,
            hops=hops, nights_per_city=nights,
            max_price_per_leg=max_leg_price, top_n=top_n,
            excluded_airports=excl_airports or None,
            excluded_countries=excl_countries or None,
        )
        return jsonify({'origin': origin, 'routes': routes})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/nomad/return')
def api_nomad_return():
    """Ищет обратные рейсы из города в home origin."""
    origin = request.args.get('origin', '').strip().upper()
    destination = request.args.get('destination', '').strip().upper()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    max_price = int(request.args.get('max_price', '50') or '50')

    if not origin or not destination or not date_from or not date_to:
        return jsonify({'error': 'origin, destination, date_from, date_to required'}), 400

    try:
        flights = searcher.search_nomad_return(
            origin=origin, destination=destination,
            date_from=date_from, date_to=date_to, max_price=max_price,
        )
        return jsonify({'flights': flights})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
