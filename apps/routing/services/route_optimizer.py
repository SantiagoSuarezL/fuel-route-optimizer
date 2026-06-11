import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.exceptions_classes import NoFuelStationError
from apps.core.utils import haversine_miles, min_distance_to_polyline

if TYPE_CHECKING:
    from apps.stations.models import FuelStation
    from apps.routing.services.route_processor import Waypoint

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class StationOnRoute:
    """
    A fuel station pinned to a specific distance along the route.

    Attributes:
        station: The FuelStation model instance.
        distance_from_start_miles: Cumulative miles from the route origin
            to the nearest waypoint on the polyline.
    """

    station: "FuelStation"
    distance_from_start_miles: float


@dataclass
class FuelStop:
    """
    One fuel purchase event, matching the API response contract exactly.

    Attributes:
        station_name: FuelStation display name.
        address: Street address of the station.
        city: City name.
        state: State abbreviation.
        latitude: Decimal latitude.
        longitude: Decimal longitude.
        price_per_gallon: Retail price per gallon (Decimal, never float).
        gallons_purchased: Gallons bought at this stop.
        stop_cost: Total cost of this stop (gallons_purchased × price).
        distance_from_start_miles: Cumulative route miles to this stop.
    """

    station_name: str
    address: str
    city: str
    state: str
    latitude: float
    longitude: float
    price_per_gallon: Decimal
    gallons_purchased: float
    stop_cost: Decimal
    distance_from_start_miles: float


# ═══════════════════════════════════════════════════════════════════════
# Spatial corridor filter — bounding box → haversine fine filter
# ═══════════════════════════════════════════════════════════════════════

class StationCorridorService:
    """
    Finds FuelStation records inside a geographic corridor around a route polyline.

    Two‑step strategy for performance:
      1. **Bounding box** on PostgreSQL — uses the composite (latitude, longitude)
         index; cheap even over 6000+ rows.
      2. **Haversine fine‑filter** in Python — precisely measures the shortest
         distance from each candidate station to the polyline and discards
         stations outside *corridor_miles*.
    """

    @staticmethod
    def _compute_bounding_box(
        waypoints: list["Waypoint"],
        corridor_miles: float,
    ) -> tuple[float, float, float, float]:
        """
        Return (min_lat, max_lat, min_lon, max_lon) padded by corridor_miles.

        Approximations used:
          - 1° latitude  ≈ 69 miles (constant)
          - 1° longitude ≈ 54 miles at ~40°N (acceptable for CONUS routes)
        """
        lats = [wp.lat for wp in waypoints]
        lons = [wp.lon for wp in waypoints]

        lat_pad = corridor_miles / 69.0
        lon_pad = corridor_miles / 54.0

        return (
            min(lats) - lat_pad,
            max(lats) + lat_pad,
            min(lons) - lon_pad,
            max(lons) + lon_pad,
        )

    def get_stations_along_route(
        self,
        waypoints: list["Waypoint"],
        corridor_miles: float,
    ) -> list[StationOnRoute]:
        """
        Return all stations within *corridor_miles* of the route polyline.

        Args:
            waypoints: Route waypoints sorted by cumulative_miles ascending.
            corridor_miles: Corridor half‑width in miles.

        Returns:
            List of StationOnRoute sorted by distance_from_start_miles ascending.
            Stations with null lat/lon are silently skipped.
        """
        if not waypoints:
            return []

        # Build (lat, lon) tuples for min_distance_to_polyline
        polyline = [(wp.lat, wp.lon) for wp in waypoints]

        bbox_min_lat, bbox_max_lat, bbox_min_lon, bbox_max_lon = (
            self._compute_bounding_box(waypoints, corridor_miles)
        )

        # Step 1 — bounding box on PostgreSQL
        from apps.stations.models import FuelStation

        candidates = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=bbox_min_lat,
            latitude__lte=bbox_max_lat,
            longitude__gte=bbox_min_lon,
            longitude__lte=bbox_max_lon,
        )

        # Step 2 — haversine fine‑filter in Python
        results: list[StationOnRoute] = []
        for station in candidates.iterator():
            dist_to_route = min_distance_to_polyline(
                station.latitude, station.longitude, polyline,
            )
            if dist_to_route <= corridor_miles:
                closest_miles = self._closest_waypoint_miles(
                    station.latitude, station.longitude, waypoints,
                )
                results.append(
                    StationOnRoute(
                        station=station,
                        distance_from_start_miles=closest_miles,
                    ),
                )

        results.sort(key=lambda s: s.distance_from_start_miles)
        return results

    @staticmethod
    def _closest_waypoint_miles(
        lat: float,
        lon: float,
        waypoints: list["Waypoint"],
    ) -> float:
        """Return cumulative_miles of the waypoint nearest to (lat, lon)."""
        best_miles = 0.0
        best_dist = float("inf")
        for wp in waypoints:
            d = haversine_miles(lat, lon, wp.lat, wp.lon)
            if d < best_dist:
                best_dist = d
                best_miles = wp.cumulative_miles
        return best_miles


# ═══════════════════════════════════════════════════════════════════════
# Greedy fuel‑stop optimiser
# ═══════════════════════════════════════════════════════════════════════

class RouteOptimizer:
    """
    Greedy algorithm that computes the cheapest sequence of fuel stops.

    **How it works:**

    1. The vehicle starts with a full tank (TANK_RANGE ÷ MPG gallons).
    2. At each decision point it looks at *all* reachable stations within
       its remaining fuel window.
    3. It picks the **cheapest** station (`retail_price`) in that window.
    4. It drives there (consuming fuel), fills the tank completely,
       records the stop, and repeats.
    5. When the destination is reachable on remaining fuel, it stops.

    The algorithm is optimal under the assumption that filling the full
    tank at the cheapest reachable station minimises the per‑mile fuel
    cost for the remainder of the trip.
    """

    def __init__(
        self,
        start_text: str,
        finish_text: str,
        total_distance_miles: float,
        geometry: dict,
        waypoints: list["Waypoint"],
        stations: list[StationOnRoute],
        tank_range_miles: float,
        mpg: float,
    ) -> None:
        """
        Args:
            start_text: Human‑readable origin (e.g. "New York, NY").
            finish_text: Human‑readable destination (e.g. "Los Angeles, CA").
            total_distance_miles: Total route length in miles.
            geometry: GeoJSON LineString from OSRM (passthrough to response).
            waypoints: Route waypoints (used for response metadata).
            stations: Pre‑filtered station list (from StationCorridorService).
            tank_range_miles: Maximum miles on a full tank (settings‑driven).
            mpg: Vehicle efficiency in miles per gallon.
        """
        self.start_text = start_text
        self.finish_text = finish_text
        self.total_distance_miles = total_distance_miles
        self.geometry = geometry
        self.waypoints = waypoints
        self.stations = stations
        self.tank_range_miles = tank_range_miles
        self.mpg = mpg

    def optimize(self) -> dict:
        """
        Execute the greedy algorithm and return the full API response dict.

        Returns:
            Dictionary with keys "route", "fuel_stops", "summary" matching
            the API response contract.

        Raises:
            NoFuelStationError: When the tank would run empty with no
                reachable station ahead.
        """
        tank_capacity = self.tank_range_miles / self.mpg  # gallons
        current_mile = 0.0
        fuel_in_tank = tank_capacity
        stops: list[FuelStop] = []
        total_cost: Decimal = Decimal("0")

        stations_sorted = sorted(
            self.stations, key=lambda s: s.distance_from_start_miles,
        )

        while current_mile < self.total_distance_miles:
            max_reachable = current_mile + fuel_in_tank * self.mpg

            # Destination reachable on remaining fuel → no more stops needed
            if max_reachable >= self.total_distance_miles:
                break

            # Stations ahead of current position but within fuel window
            candidates = [
                s
                for s in stations_sorted
                if current_mile < s.distance_from_start_miles <= max_reachable
            ]

            if not candidates:
                raise NoFuelStationError(
                    f"No fuel station found near mile {current_mile:.0f}",
                )

            # Cheapest station in the window
            best = min(candidates, key=lambda s: s.station.retail_price)

            miles_to_best = best.distance_from_start_miles - current_mile
            gallons_used = miles_to_best / self.mpg
            fuel_in_tank -= gallons_used
            gallons_to_fill = tank_capacity - fuel_in_tank

            # Financial precision: never multiply floats for money
            stop_cost: Decimal = (
                Decimal(str(round(gallons_to_fill, 6)))
                * best.station.retail_price
            )

            stops.append(
                FuelStop(
                    station_name=best.station.name,
                    address=best.station.address,
                    city=best.station.city,
                    state=best.station.state,
                    latitude=best.station.latitude,
                    longitude=best.station.longitude,
                    price_per_gallon=best.station.retail_price,
                    gallons_purchased=round(gallons_to_fill, 3),
                    stop_cost=round(stop_cost, 2),
                    distance_from_start_miles=round(best.distance_from_start_miles, 1),
                ),
            )

            total_cost += stop_cost
            fuel_in_tank = tank_capacity
            current_mile = best.distance_from_start_miles

        total_gallons = round(self.total_distance_miles / self.mpg, 3)

        return {
            "route": {
                "start": self.start_text,
                "finish": self.finish_text,
                "total_distance_miles": round(self.total_distance_miles, 1),
                "geometry": self.geometry,
            },
            "fuel_stops": [
                {
                    "station_name": s.station_name,
                    "address": s.address,
                    "city": s.city,
                    "state": s.state,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                    "price_per_gallon": s.price_per_gallon,
                    "gallons_purchased": s.gallons_purchased,
                    "stop_cost": s.stop_cost,
                    "distance_from_start_miles": s.distance_from_start_miles,
                }
                for s in stops
            ],
            "summary": {
                "total_fuel_cost_usd": round(total_cost, 2),
                "total_gallons": total_gallons,
                "number_of_stops": len(stops),
            },
        }
