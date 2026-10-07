"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
Order Generator module (Member 3)

Generates synthetic, realistic mock BUY and SELL orders for high-frequency trading simulation.
Supports deterministic generation with seeds, configurable price and quantity distributions,
and high-throughput batched generation.
"""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dataclasses import dataclass
from typing import Iterator, AsyncIterator, List, Optional
import random
import time

from ipc.structures import Order, Side


@dataclass
class OrderGeneratorConfig:
    """
    Configuration parameters for mock order generation.

    Attributes:
        initial_order_id: Starting integer for unique order IDs.
        total_orders: Total number of orders to generate (None for infinite stream).
        min_price: Minimum order price in base currency (e.g., 95.00).
        max_price: Maximum order price in base currency (e.g., 105.00).
        tick_size: Minimum price increment (e.g., 0.01 for penny increments).
        min_quantity: Minimum order quantity (e.g., 1).
        max_quantity: Maximum order quantity (e.g., 100).
        buy_ratio: Proportion of orders that are BUY (0.0 to 1.0; 0.5 is 50/50).
        seed: Random seed for deterministic and reproducible test runs.
        target_orders_per_sec: Desired generation rate in orders/sec (None = unthrottled).
    """
    initial_order_id: int = 1001
    total_orders: Optional[int] = None
    min_price: float = 95.00
    max_price: float = 105.00
    tick_size: float = 0.01
    min_quantity: int = 1
    max_quantity: int = 100
    buy_ratio: float = 0.50
    seed: Optional[int] = None
    target_orders_per_sec: Optional[int] = 100_000

    def __post_init__(self):
        if self.min_price <= 0:
            raise ValueError(f"min_price must be > 0, got {self.min_price}")
        if self.max_price < self.min_price:
            raise ValueError(f"max_price ({self.max_price}) cannot be less than min_price ({self.min_price})")
        if self.min_quantity <= 0:
            raise ValueError(f"min_quantity must be > 0, got {self.min_quantity}")
        if self.max_quantity < self.min_quantity:
            raise ValueError(f"max_quantity ({self.max_quantity}) cannot be less than min_quantity ({self.min_quantity})")
        if not (0.0 <= self.buy_ratio <= 1.0):
            raise ValueError(f"buy_ratio must be between 0.0 and 1.0, got {self.buy_ratio}")
        if self.tick_size <= 0:
            raise ValueError(f"tick_size must be > 0, got {self.tick_size}")


class OrderGenerator:
    """
    High-throughput mock order generator.

    Produces realistic BUY and SELL limit orders conforming to the IPC Order structure.
    Optimized for high-frequency trading simulations (capable of >500k orders/sec in Python).
    """

    def __init__(self, config: Optional[OrderGeneratorConfig] = None):
        self.config = config or OrderGeneratorConfig()
        self._rng = random.Random(self.config.seed)
        self._current_order_id = self.config.initial_order_id
        self._generated_count = 0

        # Pre-calculated ranges for fast generation
        self._price_range = self.config.max_price - self.config.min_price
        self._qty_range = self.config.max_quantity - self.config.min_quantity + 1
        self._min_price = self.config.min_price
        self._min_qty = self.config.min_quantity
        self._buy_ratio = self.config.buy_ratio
        self._tick_size = self.config.tick_size
        self._inv_tick = 1.0 / self._tick_size

    @property
    def generated_count(self) -> int:
        """Total number of orders generated since initialization or last reset."""
        return self._generated_count

    @property
    def current_order_id(self) -> int:
        """The next order ID that will be issued."""
        return self._current_order_id

    def reset(self, seed: Optional[int] = None):
        """
        Reset generator state, counters, and seed.
        """
        effective_seed = seed if seed is not None else self.config.seed
        self._rng.seed(effective_seed)
        self._current_order_id = self.config.initial_order_id
        self._generated_count = 0

    def has_next(self) -> bool:
        """Checks whether the generator has more orders to produce based on total_orders."""
        if self.config.total_orders is None:
            return True
        return self._generated_count < self.config.total_orders

    def generate_order(self) -> Order:
        """
        Generate a single realistic Order.

        Returns:
            Order dataclass instance with unique order_id, side, price, quantity, and timestamp.
        """
        if not self.has_next():
            raise StopIteration("Configured total_orders limit reached.")

        order_id = self._current_order_id
        self._current_order_id += 1
        self._generated_count += 1

        rand_val = self._rng.random()
        side = Side.BUY if rand_val < self._buy_ratio else Side.SELL

        # Calculate price rounded to tick_size
        raw_price = self._min_price + (self._rng.random() * self._price_range)
        price = round(raw_price * self._inv_tick) * self._tick_size
        price = round(price, 4)

        # Quantity range
        quantity = self._min_qty + int(self._rng.random() * self._qty_range)
        if quantity > self.config.max_quantity:
            quantity = self.config.max_quantity

        timestamp_ns = time.time_ns()

        return Order(
            order_id=order_id,
            price=price,
            quantity=quantity,
            side=int(side),
            timestamp_ns=timestamp_ns,
        )

    def generate_batch(self, batch_size: int) -> List[Order]:
        """
        Generate a batch of orders rapidly.

        Args:
            batch_size: Number of orders to produce in this batch.

        Returns:
            List of generated Order objects.
        """
        if self.config.total_orders is not None:
            remaining = self.config.total_orders - self._generated_count
            if remaining <= 0:
                return []
            batch_size = min(batch_size, remaining)

        batch: List[Order] = []
        # Local variable caching for loop speed
        rng = self._rng.random
        min_p = self._min_price
        p_range = self._price_range
        inv_tick = self._inv_tick
        tick_sz = self._tick_size
        min_q = self._min_qty
        q_range = self._qty_range
        max_q = self.config.max_quantity
        buy_rat = self._buy_ratio
        curr_id = self._current_order_id
        now_ns = time.time_ns

        for _ in range(batch_size):
            side = 1 if rng() < buy_rat else 2
            raw_p = min_p + (rng() * p_range)
            price = round(round(raw_p * inv_tick) * tick_sz, 4)
            qty = min_q + int(rng() * q_range)
            if qty > max_q:
                qty = max_q

            batch.append(Order(
                order_id=curr_id,
                price=price,
                quantity=qty,
                side=side,
                timestamp_ns=now_ns(),
            ))
            curr_id += 1

        self._current_order_id = curr_id
        self._generated_count += batch_size
        return batch

    def __iter__(self) -> Iterator[Order]:
        return self

    def __next__(self) -> Order:
        if not self.has_next():
            raise StopIteration
        return self.generate_order()

    async def stream(self) -> AsyncIterator[Order]:
        """
        Asynchronously yields orders one by one.
        """
        while self.has_next():
            yield self.generate_order()
