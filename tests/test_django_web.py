"""
Unit and integration tests for ChronosMatch Django Web Application and REST APIs.
"""

import os
import json
import unittest

# Ensure settings module is configured before importing Django test components
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_app.settings")

import django
django.setup()

from django.test import Client, TestCase
from django_app.engine_service import get_engine_service
from core.order_book import IS_NATIVE_CYTHON


class TestDjangoTradingTerminal(TestCase):
    """
    Test suite verifying Django terminal rendering, REST APIs,
    order submission validation, matching engine execution, and simulator lifecycle.
    """

    def setUp(self):
        self.client = Client()
        self.service = get_engine_service()
        # Reset book state before each test for test isolation
        self.service.reset_book()

    def tearDown(self):
        if self.service.simulator_running:
            self.service.stop_simulator()

    def test_terminal_homepage_renders(self):
        """Verify the main trading terminal page renders with HTTP 200 and required elements."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CHRONOS")
        self.assertContains(response, "MATCH")
        self.assertContains(response, "Order Book (L2 Depth)")
        self.assertContains(response, "Submit Simulated Order")
        self.assertContains(response, "Market Simulator Controls")

    def test_api_health_check(self):
        """Verify health check endpoint reports online status and engine mode."""
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("engine_mode", data)
        self.assertEqual(data["is_native_cython"], IS_NATIVE_CYTHON)

    def test_api_market_data_empty_book(self):
        """Verify market data feed returns clean data structure on an empty book."""
        response = self.client.get("/api/market-data/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("depth", data)
        self.assertIn("bids", data["depth"])
        self.assertIn("asks", data["depth"])
        self.assertIn("metrics", data)
        self.assertIn("latency", data["metrics"])
        self.assertIsNone(data["best_bid"])
        self.assertIsNone(data["best_ask"])
        self.assertIsNone(data["spread"])

    def test_order_submission_validation_errors(self):
        """Verify validation errors for missing fields, bad sides, negative prices, and zero quantities."""
        # 1. Missing fields
        res1 = self.client.post("/api/orders/", data=json.dumps({"price": 100.0}), content_type="application/json")
        self.assertEqual(res1.status_code, 400)
        self.assertFalse(res1.json()["success"])

        # 2. Invalid side
        res2 = self.client.post(
            "/api/orders/",
            data=json.dumps({"side": "HOLD", "price": 100.0, "quantity": 10}),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("BUY or SELL", res2.json()["error"])

        # 3. Non-positive price
        res3 = self.client.post(
            "/api/orders/",
            data=json.dumps({"side": "BUY", "price": -10.5, "quantity": 10}),
            content_type="application/json",
        )
        self.assertEqual(res3.status_code, 400)
        self.assertIn("positive", res3.json()["error"])

        # 4. Zero quantity
        res4 = self.client.post(
            "/api/orders/",
            data=json.dumps({"side": "SELL", "price": 105.0, "quantity": 0}),
            content_type="application/json",
        )
        self.assertEqual(res4.status_code, 400)
        self.assertIn("positive integer", res4.json()["error"])

    def test_order_submission_and_matching_execution(self):
        """Verify manual orders execute through Cython matching engine and update book & trades."""
        # 1. Submit resting SELL order: 50 shares @ $102.50
        res_sell = self.client.post(
            "/api/orders/",
            data=json.dumps({"side": "SELL", "price": 102.50, "quantity": 50}),
            content_type="application/json",
        )
        self.assertEqual(res_sell.status_code, 200)
        data_sell = res_sell.json()
        self.assertTrue(data_sell["success"])
        self.assertEqual(data_sell["status"], "RESTING")
        self.assertEqual(data_sell["remaining_quantity"], 50)

        # Verify market data reflects resting ask
        mkt1 = self.client.get("/api/market-data/").json()
        self.assertEqual(mkt1["best_ask"], [102.50, 50])
        self.assertIsNone(mkt1["best_bid"])

        # 2. Submit matching BUY order: 30 shares @ $103.00 (crosses book!)
        res_buy = self.client.post(
            "/api/orders/",
            data=json.dumps({"side": "BUY", "price": 103.00, "quantity": 30}),
            content_type="application/json",
        )
        self.assertEqual(res_buy.status_code, 200)
        data_buy = res_buy.json()
        self.assertTrue(data_buy["success"])
        self.assertEqual(data_buy["status"], "FILLED")
        self.assertEqual(data_buy["filled_quantity"], 30)
        self.assertEqual(data_buy["trades_count"], 1)

        # 3. Verify trade executed at resting price $102.50
        trade = data_buy["trades"][0]
        self.assertEqual(trade["price"], 102.50)
        self.assertEqual(trade["quantity"], 30)

        # 4. Verify updated market depth has 20 remaining asks @ $102.50
        mkt2 = self.client.get("/api/market-data/").json()
        self.assertEqual(mkt2["best_ask"], [102.50, 20])
        self.assertEqual(mkt2["last_price"], 102.50)
        self.assertEqual(len(mkt2["recent_trades"]), 1)
        self.assertEqual(mkt2["metrics"]["trades_executed"], 1)
        self.assertEqual(mkt2["metrics"]["total_volume"], 30)

    def test_simulator_controls_api(self):
        """Verify simulator start, duplicate start prevention, stop, and reset APIs."""
        # 1. Start simulator
        res_start = self.client.post(
            "/api/simulator/start/",
            data=json.dumps({"orders": 1000, "rate": 50000}),
            content_type="application/json",
        )
        self.assertEqual(res_start.status_code, 200)
        self.assertTrue(res_start.json()["success"])

        # 2. Duplicate start attempt should be rejected with 409 Conflict
        res_dup = self.client.post("/api/simulator/start/", data="{}", content_type="application/json")
        self.assertEqual(res_dup.status_code, 409)
        self.assertFalse(res_dup.json()["success"])

        # 3. Stop simulator
        res_stop = self.client.post("/api/simulator/stop/")
        self.assertEqual(res_stop.status_code, 200)
        self.assertTrue(res_stop.json()["success"])

        # 4. Reset book
        res_reset = self.client.post("/api/simulator/reset/")
        self.assertEqual(res_reset.status_code, 200)
        self.assertTrue(res_reset.json()["success"])

        mkt = self.client.get("/api/market-data/").json()
        self.assertEqual(mkt["metrics"]["orders_processed"], 0)
        self.assertEqual(mkt["metrics"]["trades_executed"], 0)


if __name__ == "__main__":
    unittest.main()
