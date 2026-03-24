# Ryanair FlyNomad

Cheap flights & multi-city trip planner for Ryanair. Search round trips or build multi-city routes with automatic return — all powered by Ryanair API.

![Screenshot](screenshot.png?v=2)

## Features

- **Multi-city route builder** — explore 1-4 cities with guaranteed return to origin
- **Smart return algorithm** — pre-computes returnable airports, filters last hop by return availability
- **Round-trip search** — set Cities=1 for classic cheap flight exploration
- Flexible nights per city (e.g. 1,2,3)
- Filters: max price per leg, exclude countries/airports
- Stale-While-Revalidate caching (diskcache/SQLite)
- 7 languages: EN, ES, IT, FR, PT, DE, RU
- Dark mode, responsive layout
- Geolocation — auto-select nearest airport

## How it works

1. Pick your departure airport and date
2. Set number of cities to visit (1-4) and nights per city
3. Click "Search routes"
4. Get complete round-trip routes sorted by total price

**Cities=1** — explores all cheap destinations (like Google Flights Explore)
**Cities=2-4** — builds multi-city itineraries: `origin → city1 → city2 → ... → origin`

The algorithm uses Ryanair's bidirectional route network: if Ryanair flies A→B, it also flies B→A. This `returnable_set` is computed upfront and used to filter the last hop — ensuring every route has a return flight while saving ~50% of API calls.

## Installation

```bash
pip install -r requirements.txt
```

## Web UI

```bash
python3 app.py
```

Open http://localhost:5000

## CLI

```bash
# Search flights on a specific date
python3 main.py -d 2026-05-15 -n 1,2,3

# Weekend trip
python3 main.py -d 2026-03-20 -n 2

# One-day trips
python3 main.py --one-day

# Exclude airports
python3 main.py -d 2026-05-15 -n 1,2 -e AGP,MAD
```

## Tests

```bash
# Unit tests
pytest tests/test_app.py

# Playwright E2E tests
pytest tests/test_playwright.py -v
```

## Configuration

`config.yaml`:
- `origin_airport` — departure airport (default: VLC)
- `max_price` — max ticket price (EUR)
- `excluded_countries` — countries to exclude
- `date_flexibility_days` — ±days from departure date
- `max_arrival_time_destination` — latest arrival time

## License

[MIT](LICENSE)
