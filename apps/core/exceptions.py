import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework import serializers

from apps.core.exceptions_classes import (
    GeocodingError,
    LocationNotInUSAError,
    RoutingServiceError,
    NoFuelStationError,
)

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, GeocodingError):
        logger.warning("Geocoding error: %s", exc)
        return Response(
            {"error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, LocationNotInUSAError):
        logger.warning("Location outside USA: %s", exc)
        return Response(
            {"error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, RoutingServiceError):
        logger.error("Routing service error: %s", exc)
        return Response(
            {"error": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, NoFuelStationError):
        logger.warning("No fuel station reachable: %s", exc)
        return Response(
            {"error": str(exc)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if response is not None:
        if isinstance(exc, serializers.ValidationError):
            detail = response.data
            if isinstance(detail, dict):
                errors = []
                for field, messages in detail.items():
                    for msg in messages if isinstance(messages, list) else [messages]:
                        errors.append(f"'{field}': {msg}")
                return Response(
                    {"error": "; ".join(errors)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"error": str(detail)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    return response