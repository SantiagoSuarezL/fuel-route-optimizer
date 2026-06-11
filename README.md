# Fuel Route Optimization API

A production-grade Django REST API that computes optimal fuel stops for US road trips. Given a start and finish location, it returns a full route with geometry, a sequence of fuel stops chosen by a greedy price-minimization algorithm, and a cost summary.

## Requirements

- Python 3.11+
- pip
- Docker Desktop (for the PostgreSQL 16 container)

## Setup

```bash
git clone <repo-url>
cd fuel-route-optimizer

# 1. Start PostgreSQL
docker compose up -d

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set DJANGO_SECRET_KEY to a long random string

# 5. Run migrations
python manage.py migrate

# 6. Load fuel station data (with geocoding — takes ~30–60 min)
python manage.py load_stations --csv data/fuel-prices.csv

# 6b. Quick load without geocoding (for testing — lat/lon will be null)
python manage.py load_stations --csv data/fuel-prices.csv --skip-geocoding

# 7. Start the API
python manage.py runserver
```

## API Usage

### Endpoint

```
POST /api/v1/route/
Content-Type: application/json
```

### Example Request

```bash
curl -X POST http://localhost:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "New York, NY", "finish": "Los Angeles, CA"}'
```

### Example Response

```json
{
  "route": {
    "start": "New York, NY",
    "finish": "Los Angeles, CA",
    "total_distance_miles": 2790.4,
    "geometry": {
      "type": "LineString",
      "coordinates": [[-74.006, 40.7128], [-118.2437, 34.0522]]
    }
  },
  "fuel_stops": [
    {
      "station_name": "LOVES TRAVEL STOP #450",
      "address": "I-40, EXIT 280",
      "city": "West Memphis",
      "state": "AR",
      "latitude": 35.1234,
      "longitude": -90.1234,
      "price_per_gallon": 3.325,
      "gallons_purchased": 50.0,
      "stop_cost": 166.25,
      "distance_from_start_miles": 487.2
    }
  ],
  "summary": {
    "total_fuel_cost_usd": 892.50,
    "total_gallons": 279.04,
    "number_of_stops": 6
  }
}
```

### Error Responses

| Scenario | Status | Body |
|----------|--------|------|
| Missing/blank field | 400 | `{"error": "'start' is required"}` |
| Geocoding failed | 400 | `{"error": "Could not geocode 'Fakeville, ZZ'"}` |
| Location outside USA | 400 | `{"error": "'Paris, France' is not within the USA"}` |
| OSRM unavailable | 503 | `{"error": "Routing service unavailable"}` |
| No station reachable | 422 | `{"error": "No fuel station found near mile 340"}` |

## Design Decisions

**Why OSRM (not Google Maps / Mapbox).** OSRM returns full route geometry in a single free API call with no API key required, making it ideal for development and demonstration. The `/route/v1/driving` endpoint returns both distance and a GeoJSON LineString in one request.

**Why Nominatim (not Google Geocoding).** Nominatim is free, based on OpenStreetMap data, and has generous rate limits (1 request/second). The project caches geocode results for 30 days to avoid repeated lookups for the same city/state pair.

**Greedy algorithm rationale.** At each decision point the algorithm picks the cheapest reachable station within the vehicle's remaining fuel range and fills the tank completely. This is optimal when all stations sell the same commodity (gasoline) and the only variable is price per gallon — it guarantees the lowest average cost per mile for the remainder of the trip.

**Caching strategy.** OSRM routes are cached for 24 hours (routes between major cities rarely change). Geocode results are cached for 30 days (city/state coordinates are effectively static). The cache key for OSRM uses truncated coordinates to maximize reuse.

**Two-step station query (bounding box + haversine).** A naive spatial query would compute haversine distance for every station in the database (6,700+ rows) against every route segment. Instead, the query first filters by a cheap bounding box in PostgreSQL (using lat/lon indexes), then applies precise haversine fine-filtering in Python only on the reduced candidate set.

**Why PostgreSQL over SQLite.** The production environment uses PostgreSQL for its index performance on numeric columns (lat/lon queries), concurrent connection handling, and environment parity with production deployments.

## Performance Notes

The first request to a new route incurs a ~1–3 second OSRM API call. All subsequent identical requests return instantly from cache (24-hour TTL). Station queries are sub-100ms thanks to the bounding-box pre-filter and database indexes. Geocoding (two Nominatim calls) only happens on first use per location — subsequent requests reuse cached coordinates.
