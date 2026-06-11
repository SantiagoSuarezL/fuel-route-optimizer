from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings

from apps.core.utils import min_distance_to_polyline

if TYPE_CHECKING:
    from apps.stations.models import FuelStation
    from apps.routing.services.route_processor import Waypoint


@dataclass
class StationOnRoute:
    """
    Represents a fuel station with its computed distance along the route.

    Attributes:
        station: The FuelStation model instance.
        distance_from_start_miles: Cumulative route miles to the nearest waypoint
            on the polyline (used for fuel optimization calculations).
    """

    station: "FuelStation"
    distance_from_start_miles: float


class StationQueryService:
    """
    Finds FuelStation records within a geographic corridor around a route polyline.

    Uses a two-step filter for efficiency:
      1. Bounding box query on PostgreSQL (uses lat/lon composite index, very fast)
      2. Haversine fine-filter in Python (precise corridor distance check)

    This avoids expensive spatial queries while maintaining accuracy.
    """

    def get_stations_along_route(
        self,
        waypoints: list["Waypoint"],
        corridor_miles: float,
    ) -> list[StationOnRoute]:
        """
        Return stations within corridor_miles of the route polyline.

        Args:
            waypoints: List of Waypoint objects (with lat, lon, cumulative_miles)
                sorted by cumulative_miles ascending.
            corridor_miles: Half-width of the corridor in miles (stations within
                this distance of the polyline are included).

        Returns:
            List of StationOnRoute objects sorted by distance_from_start_miles ascending.
            Only stations with valid latitude/longitude are considered.
        """
        if not waypoints:
            return []

        # Extract lat/lon tuples for the polyline (order: lat, lon)
        polyline = [(wp.lat, wp.lon) for wp in waypoints]

        # Compute bounding box with padding
        lats = [wp.lat for wp in waypoints]
        lons = [wp.lon for wp in waypoints]

        min_lat, max_lat = min(lats), max(lats)
        min_lon, max_lon = min(lons), max(lons)

        # 1 degree latitude ≈ 69 miles, 1 degree longitude ≈ 54 miles at ~40°N
        lat_pad = corridor_miles / 69.0
        lon_pad = corridor_miles / 54.0

        bbox_min_lat = min_lat - lat_pad
        bbox_max_lat = max_lat + lat_pad
        bbox_min_lon = min_lon - lon_pad
        bbox_max_lon = max_lon + lon_pad

        # Step 1: Bounding box filter via PostgreSQL (uses composite index on lat/lon)
        candidates = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=bbox_min_lat,
            latitude__lte=bbox_max_lat,
            longitude__gte=bbox_min_lon,
            longitude__lte=bbox_max_lon,
        )

        # Step 2: Haversine fine-filter in Python
        results: list[StationOnRoute] = []
        for station in candidates:
            # Station coordinates: (lat, lon)
            dist_to_route = min_distance_to_polyline(
                station.latitude, station.longitude, polyline
            )

            if dist_to_route <= corridor_miles:
                # Find the closest waypoint's cumulative miles
                distance_from_start = self._find_closest_waypoint_miles(
                    station.latitude, station.longitude, waypoints
                )

                results.append(
                    StationOnRoute(
                        station=station,
                        distance_from_start_miles=distance_from_start,
                    )
                )

        # Sort by distance along the route
        results.sort(key=lambda s: s.distance_from_start_miles)
        return results

    def _find_closest_waypoint_miles(
        self,
        lat: float,
        lon: float,
        waypoints: list["Waypoint"],
    ) -> float:
        """
        Find the cumulative_miles of the waypoint closest to the given coordinates.

        Uses simple haversine distance to each waypoint (not segment distance)
        since waypoints are dense enough for this approximation.

        Args:
            lat: Station latitude.
            lon: Station longitude.
            waypoints: List of Waypoint objects sorted by cumulative_miles.

        Returns:
            The cumulative_miles of the nearest waypoint.
        """
        if not waypoints:
            return 0.0

        min_dist = float("inf")
        closest_miles = 0.0

        for wp in waypoints:
            dist = min_distance_to_polyline(lat, lon, [(wp.lat, wp.lon)])
            if dist < min_dist:
                min_dist = dist
                closest_miles = wp.cumulative_miles

        return closest_miles


# Import at the bottom to avoid circular imports
from apps.stations.models import FuelStation