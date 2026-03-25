#!/usr/bin/env python3
"""FastAPI веб-интерфейс для поиска дешевых рейсов Ryanair."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import logging_config  # noqa: F401 — configure structlog on import
from flight_search import FlightSearcher
from models import WarmRequest, WarmResponse, ErrorResponse
from translations import (
    get_translator, detect_locale, SUPPORTED_LOCALES, OG_LOCALES,
)

log = structlog.get_logger()


# ── Background cache warming ─────────────────────────────
_warmed_origins: set[str] = set()


async def warm_origin(origin_code: str, searcher: FlightSearcher):
    """Прогревает кэш направлений для указанного аэропорта."""
    if origin_code in _warmed_origins:
        return
    _warmed_origins.add(origin_code)
    try:
        today = date.today()
        date_from = today.isoformat()
        date_to = (today + timedelta(days=14)).isoformat()
        await searcher.async_get_available_destinations(origin_code, date_from, date_to)
        log.info("cache_warmed", origin=origin_code, date_from=date_from, date_to=date_to)
    except Exception as e:
        log.warning("cache_warm_failed", origin=origin_code, error=str(e))


async def warm_cache_loop(searcher: FlightSearcher):
    """Периодический прогрев кэша для всех известных origins."""
    try:
        await warm_origin(searcher.config.get('origin_airport', 'VLC'), searcher)
    except Exception:
        pass
    while True:
        await asyncio.sleep(900)  # каждые 15 минут
        for origin in list(_warmed_origins):
            try:
                today = date.today()
                date_from = today.isoformat()
                date_to = (today + timedelta(days=14)).isoformat()
                await searcher.async_get_available_destinations(origin, date_from, date_to)
            except Exception:
                pass


def _build_airport_data(airports: list):
    """Build derived airport data structures."""
    countries = sorted({ap.country for ap in airports if ap.country})
    country_to_airports: dict[str, list[str]] = {}
    for ap in airports:
        country_to_airports.setdefault(ap.country, []).append(ap.code)
    airport_coords = {ap.code: {'lat': ap.lat, 'lng': ap.lng} for ap in airports}
    return countries, country_to_airports, airport_coords


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize searcher, load airports, start background tasks."""
    searcher = FlightSearcher()
    airports = searcher.get_airports()
    countries, country_to_airports, airport_coords = _build_airport_data(airports)

    app.state.searcher = searcher
    app.state.airports = airports
    app.state.countries = countries
    app.state.country_to_airports = country_to_airports
    app.state.airport_coords = airport_coords

    await searcher.open()
    log.info("app_started", airports=len(airports))
    task = asyncio.create_task(warm_cache_loop(searcher))
    yield
    task.cancel()
    await searcher.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def serialize_trip(trip):
    """Конвертирует Trip model в плоский словарь для шаблона."""
    out = trip.outbound
    inb = trip.inbound
    return {
        'destination': out.destination_name or out.destination,
        'dest_code': out.destination,
        'total_price': round(trip.total_price, 2),
        'currency': out.currency,
        'nights': trip.nights,
        'stay_hours': trip.stay_duration_hours,
        'out_date': out.departure_time.strftime('%d.%m.%Y'),
        'out_dep': out.departure_time.strftime('%H:%M'),
        'out_arr': out.arrival_time.strftime('%H:%M'),
        'out_flight': out.flight_number,
        'in_date': inb.departure_time.strftime('%d.%m.%Y'),
        'in_dep': inb.departure_time.strftime('%H:%M'),
        'in_arr': inb.arrival_time.strftime('%H:%M'),
        'in_flight': inb.flight_number,
    }


@app.get('/api/destinations')
async def api_destinations(request: Request):
    """Возвращает список доступных направлений из аэропорта."""
    searcher = request.app.state.searcher
    origin = request.query_params.get('origin', '').strip().upper()
    departure_date = request.query_params.get('date', '').strip()
    flex_days = int(request.query_params.get('flex', '1') or '1')

    if not origin or not departure_date:
        return JSONResponse({'error': 'origin and date required'}, status_code=400)

    await warm_origin(origin, searcher)
    try:
        dt = date.fromisoformat(departure_date)
        date_from = (dt - timedelta(days=flex_days)).isoformat()
        date_to = (dt + timedelta(days=flex_days)).isoformat()

        dests = await searcher.async_get_available_destinations(origin, date_from, date_to)

        result = [
            {'code': code, 'name': info.name, 'country': info.country, 'min_price': info.price}
            for code, info in sorted(dests.items(), key=lambda x: x[1].price)
        ]
        return {'origin': origin, 'destinations': result}
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@app.post('/api/warm')
async def api_warm(request: Request, body: WarmRequest):
    """Запускает прогрев кэша для указанного аэропорта."""
    searcher = request.app.state.searcher
    origin = body.origin.strip().upper()
    if not origin or len(origin) != 3:
        return JSONResponse({'error': 'invalid origin'}, status_code=400)
    await warm_origin(origin, searcher)
    return WarmResponse(status='warming', origin=origin)


@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    searcher = request.app.state.searcher
    airports = request.app.state.airports
    params = request.query_params
    mode = params.get('mode')
    origin = params.get('origin', '').strip().upper() or None

    excl_countries_str = params.get('excl_countries', '').strip()
    excluded_countries = [c.strip() for c in excl_countries_str.split(',') if c.strip()] if excl_countries_str else []

    excl_airports_str = params.get('excl_airports', '').strip()
    excluded_airports = [c.strip().upper() for c in excl_airports_str.split(',') if c.strip()] if excl_airports_str else []

    max_price = int(params.get('max_price', '') or str(searcher.config['max_price']))
    error = None
    results = []
    freshness = None

    if mode == 'regular':
        departure_date = params.get('departure_date', '').strip()
        nights_str = params.get('nights', '').strip()
        flex_days = int(params.get('flex_days', '1') or '1')
        destination = params.get('destination', '').strip().upper() or None

        lang = detect_locale(request)
        _ = get_translator(lang)

        if not departure_date or not nights_str:
            error = _('error_missing_fields')
        else:
            try:
                nights = [int(n.strip()) for n in nights_str.split(',')]
                if origin:
                    await warm_origin(origin, searcher)
                trips = await searcher.async_search_flights(
                    departure_date, nights,
                    origin=origin,
                    excluded_airports=excluded_airports or None,
                    excluded_countries=excluded_countries or None,
                    flex_days=flex_days,
                    max_price=max_price,
                    destination=destination,
                )
                results = [serialize_trip(t) for t in trips]
                freshness = searcher.get_data_freshness()
            except ValueError:
                error = _('error_bad_format')
            except Exception as e:
                error = _('error_search', e=e)

    lang = detect_locale(request)
    _ = get_translator(lang)

    origin_code = origin or searcher.config.get('origin_airport', 'VLC')
    origin_name = origin_code
    for ap in airports:
        if ap.code == origin_code:
            origin_name = ap.name
            break

    template_data = dict(
        results=results, error=error, searched=(mode == 'regular'),
        args=params, airports=airports,
        countries=request.app.state.countries,
        country_to_airports=request.app.state.country_to_airports,
        airport_coords=request.app.state.airport_coords,
        today=date.today().isoformat(),
        max_price=searcher.config['max_price'],
        freshness=freshness,
        origin_code=origin_code, origin_name=origin_name,
        _=_, lang=lang,
        supported_locales=SUPPORTED_LOCALES,
        og_locale=OG_LOCALES.get(lang, 'en_US'),
    )

    if request.headers.get('HX-Request'):
        return templates.TemplateResponse(request, 'partials/results.html', template_data)

    return templates.TemplateResponse(request, 'index.html', template_data)


@app.get('/api/nomad/options')
async def api_nomad_options(request: Request):
    """Возвращает top-N дешёвых one-way рейсов из аэропорта."""
    searcher = request.app.state.searcher
    params = request.query_params
    origin = params.get('origin', '').strip().upper()
    date_from = params.get('date_from', '').strip()
    date_to = params.get('date_to', '').strip()
    max_leg_price = int(params.get('max_leg_price', '50') or '50')
    top_n = int(params.get('top_n', '10') or '10')

    excl_airports_str = params.get('excl_airports', '').strip()
    excl_airports = [a.strip().upper() for a in excl_airports_str.split(',') if a.strip()] if excl_airports_str else []

    excl_countries_str = params.get('excl_countries', '').strip()
    excl_countries = [c.strip() for c in excl_countries_str.split(',') if c.strip()] if excl_countries_str else []

    if not origin or not date_from or not date_to:
        return JSONResponse({'error': 'origin, date_from, date_to required'}, status_code=400)

    await warm_origin(origin, searcher)
    try:
        options = await searcher.async_search_nomad_options(
            origin=origin, date_from=date_from, date_to=date_to,
            max_price_per_leg=max_leg_price, top_n=top_n,
            excluded_airports=excl_airports or None,
            excluded_countries=excl_countries or None,
        )
        return {'origin': origin, 'options': options}
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@app.get('/api/nomad/routes')
async def api_nomad_routes(request: Request):
    """Автоматический поиск nomad-маршрутов с возвратом."""
    searcher = request.app.state.searcher
    params = request.query_params
    origin = params.get('origin', '').strip().upper()
    departure_date = params.get('departure_date', '').strip()
    hops = int(params.get('hops', '2') or '2')
    nights_str = params.get('nights', '1,2,3').strip()
    max_leg_price = int(params.get('max_price', '50') or '50')
    top_n = int(params.get('top_n', '10') or '10')

    excl_airports_str = params.get('excl_airports', '').strip()
    excl_airports = [a.strip().upper() for a in excl_airports_str.split(',') if a.strip()] if excl_airports_str else []

    excl_countries_str = params.get('excl_countries', '').strip()
    excl_countries = [c.strip() for c in excl_countries_str.split(',') if c.strip()] if excl_countries_str else []

    if not origin or not departure_date:
        return JSONResponse({'error': 'origin and departure_date required'}, status_code=400)

    try:
        nights = [int(n.strip()) for n in nights_str.split(',') if n.strip()]
        if not nights:
            nights = [1, 2, 3]
    except ValueError:
        nights = [1, 2, 3]

    await warm_origin(origin, searcher)
    try:
        routes = await searcher.async_search_nomad_routes(
            origin=origin, departure_date=departure_date,
            hops=hops, nights_per_city=nights,
            max_price_per_leg=max_leg_price, top_n=top_n,
            excluded_airports=excl_airports or None,
            excluded_countries=excl_countries or None,
        )
        return {'origin': origin, 'routes': routes}
    except Exception as e:
        log.exception("nomad_routes_error", error=str(e))
        return JSONResponse({'error': str(e)}, status_code=500)


@app.get('/api/nomad/return')
async def api_nomad_return(request: Request):
    """Ищет обратные рейсы из города в home origin."""
    searcher = request.app.state.searcher
    params = request.query_params
    origin = params.get('origin', '').strip().upper()
    destination = params.get('destination', '').strip().upper()
    date_from = params.get('date_from', '').strip()
    date_to = params.get('date_to', '').strip()
    max_price = int(params.get('max_price', '50') or '50')

    if not origin or not destination or not date_from or not date_to:
        return JSONResponse({'error': 'origin, destination, date_from, date_to required'}, status_code=400)

    try:
        flights = await searcher.async_search_nomad_return(
            origin=origin, destination=destination,
            date_from=date_from, date_to=date_to, max_price=max_price,
        )
        return {'flights': flights}
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


@app.get('/health')
async def health():
    """Liveness probe."""
    return {'status': 'ok'}


@app.get('/ready')
async def ready(request: Request):
    """Readiness probe — checks that searcher and cache are initialized."""
    searcher = request.app.state.searcher
    airports = request.app.state.airports
    if not airports:
        return JSONResponse({'status': 'not_ready', 'reason': 'no airports loaded'}, status_code=503)
    return {'status': 'ready', 'airports': len(airports), 'cache': searcher.cache_stats()}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=5000)
