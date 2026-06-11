from django.urls import path
from apps.routing.views import OptimizeRouteView

urlpatterns = [
    path("route/", OptimizeRouteView.as_view(), name="optimize-route"),
]