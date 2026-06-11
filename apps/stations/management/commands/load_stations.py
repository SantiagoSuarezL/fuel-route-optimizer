import csv
import time
from decimal import Decimal

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.stations.models import FuelStation


class Command(BaseCommand):
    help = "Load fuel stations from CSV into PostgreSQL"

    MAX_RETRIES = 3
    RETRY_DELAY = 2.0

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="Path to the CSV file")
        parser.add_argument(
            "--skip-geocoding",
            action="store_true",
            help="Skip geocoding (sets all lat/lon to None)",
        )

    def handle(self, *args, **options):
        csv_path = options["csv"]
        skip_geocoding = options["skip_geocoding"]

        self.stdout.write(f"Loading stations from {csv_path}...")

        stations_by_opis = self._parse_and_deduplicate(csv_path)

        if skip_geocoding:
            self.stdout.write("Skipping geocoding (--skip-geocoding flag set)")
            geocode_cache = {}
        else:
            geocode_cache = self._geocode_city_state_pairs(stations_by_opis)

        self._bulk_insert_stations(stations_by_opis, geocode_cache)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Loaded {len(stations_by_opis)} stations into PostgreSQL."
            )
        )

    def _normalize_city(self, city: str) -> str:
        return city.strip().title()

    def _normalize_state(self, state: str) -> str:
        return state.strip().upper()

    def _make_geocode_key(self, city: str, state: str) -> str:
        return f"{self._normalize_city(city)}, {self._normalize_state(state)}"

    def _parse_and_deduplicate(self, csv_path):
        stations_by_opis = {}

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                opis_id = int(row["OPIS Truckstop ID"].strip())
                name = row["Truckstop Name"].strip()
                address = row["Address"].strip()
                city = self._normalize_city(row["City"])
                state = self._normalize_state(row["State"])
                rack_id = int(row["Rack ID"].strip())
                retail_price = Decimal(row["Retail Price"].strip())

                key = opis_id
                if key not in stations_by_opis:
                    stations_by_opis[key] = {
                        "opis_id": opis_id,
                        "name": name,
                        "address": address,
                        "city": city,
                        "state": state,
                        "rack_id": rack_id,
                        "retail_price": retail_price,
                    }
                elif retail_price < stations_by_opis[key]["retail_price"]:
                    stations_by_opis[key]["retail_price"] = retail_price
                    stations_by_opis[key]["name"] = name
                    stations_by_opis[key]["address"] = address
                    stations_by_opis[key]["city"] = city
                    stations_by_opis[key]["state"] = state
                    stations_by_opis[key]["rack_id"] = rack_id

        return stations_by_opis

    def _geocode_city_state_pairs(self, stations_by_opis):
        city_state_pairs = {}
        for station in stations_by_opis.values():
            city = station["city"]
            state = station["state"]
            key = self._make_geocode_key(city, state)
            if key not in city_state_pairs:
                city_state_pairs[key] = (city, state)

        total = len(city_state_pairs)
        geocode_cache = {}

        self.stdout.write(f"Geocoding {total} unique city/state pairs...")

        for idx, (key, (city, state)) in enumerate(city_state_pairs.items(), 1):
            self.stdout.write(f"  [{idx}/{total}] Geocoding: {city}, {state}")
            lat, lon = self._geocode_location(city, state)
            geocode_cache[key] = (lat, lon)

            if idx % 100 == 0 or idx == total:
                self.stdout.write(f"Geocoded {idx} / {total} city-state pairs")

            time.sleep(1.1)

        return geocode_cache

    def _geocode_location(self, city, state):
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": f"{city}, {state}, USA",
            "format": "json",
            "limit": 1,
        }
        headers = {"User-Agent": "FuelRouteAPI/1.0"}

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                if data:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"    ✓ Geocoded: {city}, {state} -> ({lat:.6f}, {lon:.6f})"
                        )
                    )
                    return lat, lon
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠ No results for '{city}, {state}' (attempt {attempt}/{self.MAX_RETRIES})"
                        )
                    )
            except requests.Timeout:
                self.stdout.write(
                    self.style.ERROR(
                        f"    ✗ Timeout geocoding '{city}, {state}' (attempt {attempt}/{self.MAX_RETRIES})"
                    )
                )
            except requests.ConnectionError:
                self.stdout.write(
                    self.style.ERROR(
                        f"    ✗ Connection error geocoding '{city}, {state}' (attempt {attempt}/{self.MAX_RETRIES})"
                    )
                )
            except requests.RequestException as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"    ✗ Request error geocoding '{city}, {state}': {e} (attempt {attempt}/{self.MAX_RETRIES})"
                    )
                )

            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        self.stdout.write(
            self.style.ERROR(f"    ✗ Failed to geocode '{city}, {state}' after {self.MAX_RETRIES} attempts")
        )
        return None, None

    def _bulk_insert_stations(self, stations_by_opis, geocode_cache):
        instances = []

        for station_data in stations_by_opis.values():
            city = station_data["city"]
            state = station_data["state"]
            key = self._make_geocode_key(city, state)
            lat, lon = geocode_cache.get(key, (None, None))

            instances.append(
                FuelStation(
                    opis_id=station_data["opis_id"],
                    name=station_data["name"],
                    address=station_data["address"],
                    city=city,
                    state=state,
                    rack_id=station_data["rack_id"],
                    retail_price=station_data["retail_price"],
                    latitude=lat,
                    longitude=lon,
                )
            )

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(instances, batch_size=500)