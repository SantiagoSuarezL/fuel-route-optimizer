import logging
import requests
from django.conf import settings
from django.core.cache import cache

from apps.core.exceptions_classes import RoutingServiceError

logger = logging.getLogger(__name__)


class OSRMClient:
    """
    Wraps a single OSRM /route/v1/driving call.
    Result cached with ROUTE_CACHE_TTL.
    Cache key format: "osrm:<lat1:.4f>,<lon1:.4f>:<lat2:.4f>,<lon2:.4f>"
    """

    def __init__(self) -> None:
        self.base_url = settings.FUEL_ROUTE["OSRM_BASE_URL"].rstrip("/")
        self.cache_ttl = settings.FUEL_ROUTE["ROUTE_CACHE_TTL"]
        self.session = requests.Session()

    def _make_cache_key(
        self,
        start: tuple[float, float],
        finish: tuple[float, float],
    ) -> str:
        """
        Generate a cache key from start and finish coordinates.

        Args:
            start: Tuple of (latitude, longitude) for origin.
            finish: Tuple of (latitude, longitude) for destination.

        Returns:
            Cache key string with "osrm:" prefix.
        """
        lat1, lon1 = start
        lat2, lon2 = finish
        return f"osrm:{lat1:.4f},{lon1:.4f}:{lat2:.4f},{lon2:.4f}"

    def get_route(
        self,
        start: tuple[float, float],   # (latitude, longitude)
        finish: tuple[float, float],  # (latitude, longitude)
    ) -> dict:
        """
        Make one GET request to OSRM and return route details.

        Args:
            start: Tuple of (latitude, longitude) for origin.
            finish: Tuple of (latitude, longitude) for destination.

        Returns:
            Dictionary containing:
            - distance_meters: Route distance in meters (float)
            - duration_seconds: Route duration in seconds (float)
            - geometry: Google Encoded Polyline string (str)

        Raises:
            RoutingServiceError: On any requests.RequestException, non-200 status,
                or if OSRM returns a non-"Ok" response code.
        """
        cache_key = self._make_cache_key(start, finish)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        lon1, lat1 = start[1], start[0]
        lon2, lat2 = finish[1], finish[0]

        url = f"{self.base_url}/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
        params = {
            "overview": "full",
            "geometries": "polyline",
            "annotations": "distance",
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(
                "OSRM route request failed for %s -> %s: %s (type: %s)",
                start,
                finish,
                e,
                type(e).__name__,
            )
            raise RoutingServiceError("Routing service unavailable") from e

        data = response.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            logger.error(
                "OSRM returned error for %s -> %s: code=%s, message=%s",
                start,
                finish,
                data.get("code"),
                data.get("message", "N/A"),
            )
            raise RoutingServiceError("Routing service unavailable")

        route = data["routes"][0]
        result = {
            "distance_meters": float(route["distance"]),
            "duration_seconds": float(route["duration"]),
            "geometry": route["geometry"],
        }

        cache.set(cache_key, result, self.cache_ttl)
        return result