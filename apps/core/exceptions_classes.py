class FuelRouteAPIError(Exception):
    """Base exception for Fuel Route API errors."""


class GeocodingError(FuelRouteAPIError):
    """Raised when Nominatim cannot geocode a location."""


class LocationNotInUSAError(FuelRouteAPIError):
    """Raised when a geocoded location falls outside the USA."""


class RoutingServiceError(FuelRouteAPIError):
    """Raised when OSRM routing service is unavailable or returns an error."""


class NoFuelStationError(FuelRouteAPIError):
    """Raised when no fuel station is reachable before the tank runs empty."""