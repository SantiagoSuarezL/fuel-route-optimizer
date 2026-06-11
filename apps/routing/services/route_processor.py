from dataclasses import dataclass

from apps.core.utils import haversine_miles, decode_polyline


@dataclass
class Waypoint:
    """
    Represents a point along the route with cumulative mileage from the start.

    Attributes:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        cumulative_miles: Total distance in miles from the route start to this point.
    """

    lat: float
    lon: float
    cumulative_miles: float


class RouteProcessor:
    """
    Converts an OSRM route dict into a list of Waypoints with cumulative mileage.

    The OSRM response contains a Google Encoded Polyline geometry string.
    This class decodes the polyline and computes cumulative mileage using
    OSRM's pre-calculated leg distances (annotations=distance) when available,
    falling back to haversine distance between consecutive points.
    """

    def __init__(self, osrm_route: dict) -> None:
        """
        Initialize with the raw OSRM route response.

        Args:
            osrm_route: Dictionary returned by OSRMClient.get_route containing
                "distance_meters", "duration_seconds", "geometry" (polyline string),
                and optionally "legs" with "annotation.distance" array.
        """
        self._osrm_route = osrm_route
        self._waypoints: list[Waypoint] | None = None

    @property
    def total_miles(self) -> float:
        """
        Total route distance in miles derived from waypoints.

        Returns:
            Total distance in miles from the first to the last waypoint.
            Returns 0.0 if no waypoints are available.
        """
        waypoints = self.get_waypoints()
        if not waypoints:
            return 0.0
        return waypoints[-1].cumulative_miles

    def get_waypoints(self) -> list[Waypoint]:
        """
        Parse the geometry (Google Encoded Polyline) and compute cumulative mileage.

        Uses OSRM's pre-calculated leg distances (annotations=distance) to avoid
        computing haversine for every segment in Python. Falls back to haversine
        if annotations are missing.

        Returns:
            List of Waypoint objects sorted by cumulative_miles ascending.
            Returns empty list if geometry is missing or malformed.
        """
        if self._waypoints is not None:
            return self._waypoints

        geometry = self._osrm_route.get("geometry")
        if not geometry or not isinstance(geometry, str):
            self._waypoints = []
            return self._waypoints

        try:
            coordinates = decode_polyline(geometry)
        except Exception:
            self._waypoints = []
            return self._waypoints

        if not coordinates:
            self._waypoints = []
            return self._waypoints

        # Use OSRM's pre-calculated leg distances (in meters) if available
        leg_distances = self._osrm_route.get("legs", [])
        segment_miles_list: list[float] = []

        if leg_distances and "annotation" in leg_distances[0] and "distance" in leg_distances[0]["annotation"]:
            # OSRM returned leg distances - convert meters to miles
            distances_meters = leg_distances[0]["annotation"]["distance"]
            segment_miles_list = [d / 1609.344 for d in distances_meters]
        else:
            # Fallback: compute haversine for each segment
            segment_miles_list = [
                haversine_miles(coordinates[i][0], coordinates[i][1], coordinates[i + 1][0], coordinates[i + 1][1])
                for i in range(len(coordinates) - 1)
            ]

        # Build waypoints with cumulative miles using accumulate pattern
        waypoints: list[Waypoint] = []
        cumulative = 0.0

        # First point
        first_lat, first_lon = coordinates[0]
        waypoints.append(Waypoint(lat=first_lat, lon=first_lon, cumulative_miles=cumulative))

        # Remaining points
        for i, segment_miles in enumerate(segment_miles_list):
            cumulative += segment_miles
            curr_lat, curr_lon = coordinates[i + 1]
            waypoints.append(Waypoint(lat=curr_lat, lon=curr_lon, cumulative_miles=cumulative))

        self._waypoints = waypoints
        return waypoints