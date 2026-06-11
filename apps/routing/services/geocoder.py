import logging
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils.text import slugify

from apps.core.exceptions_classes import GeocodingError, LocationNotInUSAError

logger = logging.getLogger(__name__)


class NominatimGeocoder:
    """
    Wraps the Nominatim /search endpoint.
    Responses are cached in Django's cache backend (GEOCODE_CACHE_TTL).
    Cache key format: "geocode:<slugified-lowercase-location>"
    """

    USA_BBOXES = [
        (24.39, 49.38, -124.85, -66.88),   # Contiguous USA
        (51.0, 71.5, -180.0, -129.9),       # Alaska
        (18.9, 22.2, -160.3, -154.8),       # Hawaii
    ]

    def __init__(self) -> None:
        self.base_url = settings.FUEL_ROUTE["NOMINATIM_BASE_URL"].rstrip("/")
        self.cache_ttl = settings.FUEL_ROUTE["GEOCODE_CACHE_TTL"]
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "FuelRouteAPI/1.0"})

    def _make_cache_key(self, location_text: str) -> str:
        """
        Generate a cache key from the location text using Django's slugify.

        Args:
            location_text: Free-text location string (e.g., "Chicago, IL").

        Returns:
            Cache key string with "geocode:" prefix.
        """
        slug = slugify(location_text.strip().lower())
        return f"geocode:{slug}"

    def _is_in_usa(self, lat: float, lon: float) -> bool:
        """
        Check if coordinates fall within any USA bounding box.

        Args:
            lat: Latitude in decimal degrees.
            lon: Longitude in decimal degrees.

        Returns:
            True if inside USA bounding boxes, False otherwise.
        """
        for min_lat, max_lat, min_lon, max_lon in self.USA_BBOXES:
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                return True
        return False

    def geocode(self, location_text: str) -> tuple[float, float]:
        """
        Return (latitude, longitude) for a free-text US location string.

        Args:
            location_text: Location query string (e.g., "New York, NY").

        Returns:
            Tuple of (latitude, longitude) as floats.

        Raises:
            GeocodingError: If Nominatim returns no results or request fails.
            LocationNotInUSAError: If the top result falls outside USA bounding boxes.
        """
        cache_key = self._make_cache_key(location_text)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "q": f"{location_text.strip()}, USA",
            "format": "json",
            "limit": 1,
        }

        try:
            response = self.session.get(
                f"{self.base_url}/search",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(
                "Nominatim geocode request failed for '%s': %s (type: %s)",
                location_text,
                e,
                type(e).__name__,
            )
            raise GeocodingError(f"Could not geocode '{location_text}'") from e

        data = response.json()
        if not data:
            logger.warning("Nominatim returned empty results for '%s'", location_text)
            raise GeocodingError(f"Could not geocode '{location_text}'")

        lat = float(data[0]["lat"])
        lon = float(data[0]["lon"])

        if not self._is_in_usa(lat, lon):
            logger.warning(
                "Geocoded location '%s' resolved to (%.4f, %.4f) outside USA bounding boxes",
                location_text,
                lat,
                lon,
            )
            raise LocationNotInUSAError(f"'{location_text}' is not within the USA")

        result = (lat, lon)
        cache.set(cache_key, result, self.cache_ttl)
        return result