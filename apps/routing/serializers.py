from decimal import Decimal
from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=255,
        required=True,
        help_text="Starting location (e.g., 'New York, NY')",
    )
    finish = serializers.CharField(
        max_length=255,
        required=True,
        help_text="Destination location (e.g., 'Los Angeles, CA')",
    )


class FuelStopSerializer(serializers.Serializer):
    station_name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    price_per_gallon = serializers.DecimalField(
        max_digits=8, decimal_places=5, coerce_to_string=False
    )
    gallons_purchased = serializers.FloatField()
    stop_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, coerce_to_string=False
    )
    distance_from_start_miles = serializers.FloatField()


class RouteDetailSerializer(serializers.Serializer):
    start = serializers.CharField()
    finish = serializers.CharField()
    total_distance_miles = serializers.FloatField()
    geometry = serializers.CharField()


class SummarySerializer(serializers.Serializer):
    total_fuel_cost_usd = serializers.DecimalField(
        max_digits=10, decimal_places=2, coerce_to_string=False
    )
    total_gallons = serializers.FloatField()
    number_of_stops = serializers.IntegerField()


class RouteResponseSerializer(serializers.Serializer):
    route = RouteDetailSerializer()
    fuel_stops = FuelStopSerializer(many=True)
    summary = SummarySerializer()


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField()
