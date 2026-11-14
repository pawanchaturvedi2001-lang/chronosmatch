"""
ChronosMatch Web Terminal Views
Provides interface rendering and API endpoints for market data, order submission,
and simulator management.
"""

from django.shortcuts import render
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
import json
import time

from core.order_book import IS_NATIVE_CYTHON
from django_app.engine_service import get_engine_service


def terminal_view(request: HttpRequest) -> HttpResponse:
    """
    Renders the primary web trading terminal interface.
    """
    context = {
        "engine_mode": "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK",
        "is_native_cython": IS_NATIVE_CYTHON,
        "title": "ChronosMatch Trading Terminal",
    }
    return render(request, "django_app/terminal.html", context)


@require_GET
def health_check(request: HttpRequest) -> JsonResponse:
    """
    Status endpoint for server health and engine availability.
    """
    service = get_engine_service()
    return JsonResponse({
        "status": "online",
        "system": "ChronosMatch Zero-Copy HFT Engine",
        "engine_mode": "CYTHON NATIVE" if IS_NATIVE_CYTHON else "PURE PYTHON FALLBACK",
        "is_native_cython": IS_NATIVE_CYTHON,
        "simulator_running": service.simulator_running,
        "orders_processed": service.orders_processed,
        "trades_executed": service.trades_executed,
        "uptime_sec": round(time.time() - service.start_time, 1),
    })


@require_GET
def market_overview_api(request: HttpRequest) -> JsonResponse:
    """
    GET /api/market/
    Market overview returning current price, session high/low, best bid/ask, and spread.
    """
    service = get_engine_service()
    data = service.get_market_overview()
    return JsonResponse(data)


@require_GET
def orderbook_api(request: HttpRequest) -> JsonResponse:
    """
    GET /api/orderbook/
    Level 2 order book depth with bids and asks lists.
    """
    levels = request.GET.get("levels", 20)
    try:
        levels = max(1, min(100, int(levels)))
    except (ValueError, TypeError):
        levels = 20

    service = get_engine_service()
    data = service.get_orderbook_data(levels=levels)
    return JsonResponse(data)


@require_GET
def trades_api(request: HttpRequest) -> JsonResponse:
    """
    GET /api/trades/
    Recent executed trades tape.
    """
    limit = request.GET.get("limit", 50)
    try:
        limit = max(1, min(200, int(limit)))
    except (ValueError, TypeError):
        limit = 50

    service = get_engine_service()
    data = service.get_trades_data(limit=limit)
    return JsonResponse(data)


@require_GET
def metrics_api(request: HttpRequest) -> JsonResponse:
    """
    GET /api/metrics/
    Real-time throughput and microsecond latency percentiles.
    """
    service = get_engine_service()
    data = service.get_metrics_data()
    return JsonResponse(data)


@require_GET
def sweeps_api(request: HttpRequest) -> JsonResponse:
    """
    GET /api/sweeps/
    Whale sweep detection events and history.
    """
    limit = request.GET.get("limit", 20)
    try:
        limit = max(1, min(100, int(limit)))
    except (ValueError, TypeError):
        limit = 20

    service = get_engine_service()
    data = service.get_sweeps_data(limit=limit)
    return JsonResponse(data)


@require_GET
def market_data_feed(request: HttpRequest) -> JsonResponse:
    """
    GET /api/market-data/
    Real-time consolidated market data feed returning current book depth, best bid/ask,
    recent trades, throughput, and latency percentiles.
    """
    service = get_engine_service()
    data = service.get_market_data()
    return JsonResponse(data)


@csrf_exempt
@require_POST
def submit_order_api(request: HttpRequest) -> JsonResponse:
    """
    Submits a simulated BUY or SELL manual order to the matching engine.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

    side = payload.get("side")
    price = payload.get("price")
    quantity = payload.get("quantity")

    if side is None or price is None or quantity is None:
        return JsonResponse(
            {"success": False, "error": "Missing required fields: 'side', 'price', and 'quantity'."},
            status=400,
        )

    service = get_engine_service()
    result = service.submit_manual_order(side_str=side, price=price, quantity=quantity)
    status_code = 200 if result.get("success") else 400
    return JsonResponse(result, status=status_code)


@csrf_exempt
@require_POST
def start_simulator_api(request: HttpRequest) -> JsonResponse:
    """
    Starts the asynchronous market simulator background producer and consumer.
    """
    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}

    orders = payload.get("orders", 5000)
    rate = payload.get("rate", 25000)

    try:
        orders = int(orders)
        rate = int(rate)
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "error": "Orders and rate must be valid integers."}, status=400)

    service = get_engine_service()
    success, message = service.start_simulator(total_orders=orders, target_rate=rate)
    status_code = 200 if success else 409
    return JsonResponse({"success": success, "message": message}, status=status_code)


@csrf_exempt
@require_POST
def stop_simulator_api(request: HttpRequest) -> JsonResponse:
    """
    Stops an active background market simulator.
    """
    service = get_engine_service()
    success, message = service.stop_simulator()
    status_code = 200 if success else 400
    return JsonResponse({"success": success, "message": message}, status=status_code)


@csrf_exempt
@require_POST
def reset_book_api(request: HttpRequest) -> JsonResponse:
    """
    Resets the Limit Order Book and trade tape to a clean initial state.
    """
    service = get_engine_service()
    success, message = service.reset_book()
    return JsonResponse({"success": success, "message": message})

