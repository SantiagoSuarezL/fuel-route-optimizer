import logging
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.serializers import (
    RouteRequestSerializer,
    RouteResponseSerializer,
)
from apps.routing.services.geocoder import NominatimGeocoder
from apps.routing.services.osrm_client import OSRMClient
from apps.routing.services.route_processor import RouteProcessor
from apps.routing.services.route_optimizer import (
    StationCorridorService,
    RouteOptimizer,
)

logger = logging.getLogger(__name__)


class OptimizeRouteView(APIView):
    def post(self, request):
        req_serializer = RouteRequestSerializer(data=request.data)
        req_serializer.is_valid(raise_exception=True)

        start_text = req_serializer.validated_data["start"]
        finish_text = req_serializer.validated_data["finish"]

        geocoder = NominatimGeocoder()
        start_coords = geocoder.geocode(start_text)
        finish_coords = geocoder.geocode(finish_text)

        osrm = OSRMClient()
        osrm_route = osrm.get_route(start_coords, finish_coords)

        processor = RouteProcessor(osrm_route)
        waypoints = processor.get_waypoints()
        total_miles = processor.total_miles

        corridor = StationCorridorService()
        stations = corridor.get_stations_along_route(
            waypoints,
            settings.FUEL_ROUTE["CORRIDOR_WIDTH_MILES"],
        )

        optimizer = RouteOptimizer(
            start_text=start_text,
            finish_text=finish_text,
            total_distance_miles=total_miles,
            geometry=osrm_route["geometry"],
            waypoints=waypoints,
            stations=stations,
            tank_range_miles=settings.FUEL_ROUTE["TANK_RANGE_MILES"],
            mpg=settings.FUEL_ROUTE["MPG"],
        )

        result = optimizer.optimize()

        resp_serializer = RouteResponseSerializer(result)
        return Response(resp_serializer.data, status=status.HTTP_200_OK)
