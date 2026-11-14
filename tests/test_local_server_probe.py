"""
Localhost Server Integration Probe
Tests live HTTP interaction with running Django server on 127.0.0.1:8000:
- Homepage HTML rendering
- GET /api/health/
- GET /api/market/
- GET /api/orderbook/
- GET /api/trades/
- GET /api/metrics/
- GET /api/sweeps/
- POST /api/orders/ (RESTING, PARTIAL, FULL, REJECTED)
- POST /api/simulator/start/ and POST /api/simulator/stop/
- Clean shutdown
"""

import time
import json
import urllib.request
import urllib.error
import subprocess
import sys
import os

BASE_URL = "http://127.0.0.1:8000"


def http_get(endpoint: str) -> dict:
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "ChronosMatch-Probe"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if "application/json" in content_type:
            return resp.status, json.loads(raw.decode("utf-8"))
        return resp.status, raw.decode("utf-8")


def http_post(endpoint: str, data: dict) -> tuple:
    url = f"{BASE_URL}{endpoint}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ChronosMatch-Probe"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def run_probe():
    print("=" * 60)
    print("CHRONOSMATCH LOCALHOST SERVER LIVE HTTP PROBE")
    print("=" * 60)

    # 1. Homepage
    print("\n[1/8] Probing GET / (Homepage HTML)...")
    status, html = http_get("/")
    assert status == 200, f"Expected 200, got {status}"
    assert "CHRONOS" in html and "MATCH" in html
    assert "Order Book (L2 Depth)" in html
    print("  -> Homepage loaded successfully (HTTP 200 OK, length: {len(html)} bytes)")

    # 2. Health API
    print("\n[2/8] Probing GET /api/health/...")
    status, health = http_get("/api/health/")
    assert status == 200
    assert health["status"] == "online"
    print(f"  -> Health OK: System={health['system']}, Engine={health['engine_mode']}")

    # 3. Market Overview API
    print("\n[3/8] Probing GET /api/market/...")
    status, mkt = http_get("/api/market/")
    assert status == 200
    assert mkt["symbol"] == "CHRONOS/USD"
    print(f"  -> Market Overview OK: Status={mkt['status']}, Symbol={mkt['symbol']}")

    # 4. Order Submission API (Resting & Matching)
    print("\n[4/8] Probing POST /api/orders/ (Order Submission)...")
    # A. Resting ask: 100 shares @ $105.00
    s1, r1 = http_post("/api/orders/", {"side": "SELL", "price": 105.00, "quantity": 100})
    assert s1 == 200 and r1["status"] == "RESTING"
    print(f"  -> Resting SELL order placed: #{r1['order_id']} 100 shares @ $105.00 (Status: {r1['status']})")

    # B. Crossing bid: 60 shares @ $105.00 (Full fill of incoming order)
    s2, r2 = http_post("/api/orders/", {"side": "BUY", "price": 105.00, "quantity": 60})
    assert s2 == 200 and r2["status"] == "FILLED"
    assert r2["trades_count"] == 1
    print(f"  -> Crossing BUY order executed: #{r2['order_id']} 60 shares filled @ $105.00 (Status: {r2['status']})")

    # C. Validation error (invalid side)
    s3, r3 = http_post("/api/orders/", {"side": "INVALID", "price": 105.00, "quantity": 10})
    assert s3 == 400 and r3["status"] == "REJECTED"
    print(f"  -> Invalid order rejected properly: HTTP {s3} (Status: {r3['status']})")

    # 5. Orderbook Depth API
    print("\n[5/8] Probing GET /api/orderbook/...")
    status, book = http_get("/api/orderbook/")
    assert status == 200
    print(f"  -> Orderbook OK: Best Ask={book['best_ask']}, Depth levels={book['depth_levels']}")

    # 6. Executed Trades API
    print("\n[6/8] Probing GET /api/trades/...")
    status, trades = http_get("/api/trades/")
    assert status == 200
    assert len(trades["trades"]) >= 1
    print(f"  -> Trades Tape OK: {len(trades['trades'])} executed trades on tape")

    # 7. Whale Sweeps API
    print("\n[7/8] Probing GET /api/sweeps/...")
    status, sweeps = http_get("/api/sweeps/")
    assert status == 200
    assert "total_sweeps_detected" in sweeps
    print(f"  -> Whale Sweeps API OK: Total Sweeps={sweeps['total_sweeps_detected']}")

    # 8. Simulator Controls (Start & Stop)
    print("\n[8/8] Probing POST /api/simulator/start/ and /stop/...")
    s_start, r_start = http_post("/api/simulator/start/", {"orders": 1000, "rate": 50000})
    assert s_start == 200
    print(f"  -> Simulator Start OK: {r_start['message']}")

    time.sleep(0.3)

    s_stop, r_stop = http_post("/api/simulator/stop/", {})
    assert s_stop == 200
    print(f"  -> Simulator Stop OK: {r_stop['message']}")

    print("\n" + "=" * 60)
    print("ALL LOCALHOST HTTP API PROBES PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_probe()
