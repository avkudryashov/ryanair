# Finding Cheap Ryanair Flights from Valencia

## Installation
```bash
pip install -r requirements.txt
```

## Usage

### Basic Examples
```bash
# Search for flights on a specific date with different stay durations
python3 main.py -d 2026-02-15 -n 1,2,3

# Weekend trip (2 nights)
python3 main.py -d 2026-03-20 -n 2

# Single night stay
python3 main.py -d 2026-04-10 -n 1
```

### One-Day Trips
```bash
# Find one-day trips with overnight stay (searches 2 months ahead)
python3 main.py --one-day

# One-day trips excluding specific airports (e.g., Ibiza, Palma)
python3 main.py --one-day -e IBZ,PMI

# One-day trips excluding multiple destinations
python3 main.py --one-day -e BCN,MAD,SVQ
```

### Advanced Usage
```bash
# Exclude specific airports from regular search
python3 main.py -d 2026-05-15 -n 1,2,3 -e AGP,MAD

# Use custom configuration file
python3 main.py -d 2026-06-01 -n 3 -c custom_config.yaml

# Long weekend search (3-4 nights) excluding islands
python3 main.py -d 2026-07-01 -n 3,4 -e IBZ,PMI,ACE
```

### Configuration
Settings in `config.yaml`:
- `max_price`: Maximum ticket price filter
- `excluded_countries`: Countries to exclude from search
- `origin_airport`: Departure airport (default: Valencia)
- `date_range_days`: Days to expand search around departure date (±N days)
- `latest_arrival_time`: Latest acceptable arrival time at destination
