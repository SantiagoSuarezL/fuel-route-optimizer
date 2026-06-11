from dataclasses import dataclass

from apps.core.utils import haversine_miles


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

    The OSRM response contains a GeoJSON LineString geometry with coordinates
    in [longitude, latitude] order. This class parses those coordinates and
    computes cumulative mileage using haversine distance between consecutive points.
    """

    def __init__(self, osrm_route: dict) -> None:
        """
        Initialize with the raw OSRM route response.

        Args:
            osrm_route: Dictionary returned by OSRMClient.get_route containing
                "distance_meters", "duration_seconds", and "geometry" (GeoJSON LineString).
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
        Parse the GeoJSON LineString and compute cumulative mileage at every point.

        The geometry coordinates are in [longitude, latitude] order per GeoJSON spec.
        We convert to (latitude, longitude) and compute cumulative distance using
        haversine_miles between consecutive coordinate pairs.

        Returns:
            List of Waypoint objects sorted by cumulative_miles ascending.
            Returns empty list if geometry is missing or malformed.
        """
        if self._waypoints is not None:
            return self._waypoints

        geometry = self._osrm_route.get("geometry")
        if not geometry or geometry.get("type") != "LineString":
            self._waypoints = []
            return self._waypoints

        coordinates = geometry.get("coordinates", [])
        if not coordinates:
            self._waypoints = []
            return self._waypoints

        waypoints: list[Waypoint] = []
        cumulative = 0.0

        # First point has cumulative 0
        first_lon, first_lat = coordinates[0]
        waypoints.append(Waypoint(lat=first_lat, lon=first_lon, cumulative_miles=cumulative))

        # Iterate through remaining points, computing segment distances
        for i in range(1, len(coordinates)):
            prev_lon, prev_lat = coordinates[i - 1]
            curr_lon, curr_lat = coordinates[i]

            segment_miles = haversine_miles(prev_lat, prev_lon, curr_lat, curr_lon)
            cumulative += segment_miles

            waypoints.append(Waypoint(lat=curr_lat, lon=curr_lon, cumulative_miles=cumulative))

        self._waypoints = waypoints
        return waypoints