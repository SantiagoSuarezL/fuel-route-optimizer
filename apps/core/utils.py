import math


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in miles between two lat/lon points.

    Args:
        lat1: Latitude of point 1 in degrees.
        lon1: Longitude of point 1 in degrees.
        lat2: Latitude of point 2 in degrees.
        lon2: Longitude of point 2 in degrees.

    Returns:
        Distance in miles (Earth radius = 3958.8 mi).
    """
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(min(1, math.sqrt(a)))

    return 3958.8 * c


def point_to_segment_distance_miles(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Return the shortest distance in miles from point P to line segment A->B.

    Uses flat-earth projection for interpolation (acceptable for segments < 200 mi),
    then haversine for the final scalar distance.

    Coordinate convention (GIS standard):
        X = Longitude (horizontal axis)
        Y = Latitude  (vertical axis)

    Args:
        px: Longitude of point P (X).
        py: Latitude of point P (Y).
        ax: Longitude of segment start A (X).
        ay: Latitude of segment start A (Y).
        bx: Longitude of segment end B (X).
        by: Latitude of segment end B (Y).

    Returns:
        Minimum distance in miles from point P to segment A-B.
    """
    if ax == bx and ay == by:
        return haversine_miles(py, px, ay, ax)

    lat_mid = (ay + by) / 2.0
    lon_scale = math.cos(math.radians(lat_mid))

    px_proj = px * lon_scale
    py_proj = py
    ax_proj = ax * lon_scale
    ay_proj = ay
    bx_proj = bx * lon_scale
    by_proj = by

    abx = bx_proj - ax_proj
    aby = by_proj - ay_proj
    apx = px_proj - ax_proj
    apy = py_proj - ay_proj

    ab_squared = abx * abx + aby * aby
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_squared))

    closest_x_proj = ax_proj + t * abx
    closest_y = ay_proj + t * aby

    closest_lon = closest_x_proj / lon_scale
    closest_lat = closest_y

    return haversine_miles(py, px, closest_lat, closest_lon)


def min_distance_to_polyline(
    lat: float,
    lon: float,
    waypoints: list[tuple[float, float]],
) -> float:
    """Return the minimum distance in miles from (lat, lon) to any segment
    of the polyline defined by waypoints.

    Args:
        lat: Latitude of the query point.
        lon: Longitude of the query point.
        waypoints: List of (lat, lon) tuples defining the polyline vertices.

    Returns:
        Minimum distance in miles to any segment of the polyline.
        Returns infinity if waypoints is empty.
    """
    if not waypoints:
        return float("inf")

    if len(waypoints) == 1:
        return haversine_miles(lat, lon, waypoints[0][0], waypoints[0][1])

    min_dist = float("inf")
    for i in range(len(waypoints) - 1):
        ay, ax = waypoints[i]
        by, bx = waypoints[i + 1]
        dist = point_to_segment_distance_miles(lon, lat, ax, ay, bx, by)
        if dist < min_dist:
            min_dist = dist

    return min_dist


def meters_to_miles(meters: float) -> float:
    """Convert meters to miles.

    Args:
        meters: Distance in meters.

    Returns:
        Distance in miles (1 mile = 1609.344 m).
    """
    return meters / 1609.344