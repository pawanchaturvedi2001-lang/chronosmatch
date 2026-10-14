"""
URL configuration for ChronosMatch Web Terminal.
"""

from django.urls import path
from django_app import views

urlpatterns = [
    path("", views.terminal_view, name="terminal"),
    path("api/health/", views.health_check, name="api_health"),
    path("api/market-data/", views.market_data_feed, name="api_market_data"),
    path("api/orders/", views.submit_order_api, name="api_submit_order"),
    path("api/simulator/start/", views.start_simulator_api, name="api_simulator_start"),
    path("api/simulator/stop/", views.stop_simulator_api, name="api_simulator_stop"),
    path("api/simulator/reset/", views.reset_book_api, name="api_simulator_reset"),
]
