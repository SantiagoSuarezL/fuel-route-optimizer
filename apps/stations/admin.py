from django.contrib import admin
from apps.stations.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state", "retail_price", "latitude", "longitude")
    list_filter = ("state",)
    search_fields = ("name", "city")