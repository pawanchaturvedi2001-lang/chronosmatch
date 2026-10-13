"""
ChronosMatch Core Models
Trade representation and Level 2 Price Level data structures.
Reuses the binary Order and Side representations from ipc.structures.
"""

from dataclasses import dataclass
import time
from typing import Dict, Any

from ipc.structures import Order, Side, SIDE_BUY, SIDE_SELL


@dataclass(slots=True)
class Trade:
    """
    Represents an executed trade between a buy order and a sell order.

    Attributes:
        trade_id: Unique sequential integer ID for the trade.
        price: Execution price (determined by the resting order's limit price).
        quantity: Executed quantity / number of shares.
        buy_order_id: Order ID of the buy side participant.
        sell_order_id: Order ID of the sell side participant.
        timestamp_ns: Nanosecond execution timestamp.
    """
    trade_id: int
    price: float
    quantity: int
    buy_order_id: int
    sell_order_id: int
    timestamp_ns: int = 0

    def __post_init__(self):
        if self.timestamp_ns == 0:
            object.__setattr__(self, "timestamp_ns", time.time_ns())

    def to_dict(self) -> Dict[str, Any]:
        """Convert trade to a dictionary representation."""
        return {
            "trade_id": self.trade_id,
            "price": self.price,
            "quantity": self.quantity,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "timestamp_ns": self.timestamp_ns,
        }

    def __repr__(self) -> str:
        return (
            f"Trade(id={self.trade_id} @ {self.price:.2f} qty={self.quantity} "
            f"buy={self.buy_order_id} sell={self.sell_order_id} ts={self.timestamp_ns})"
        )


@dataclass(slots=True)
class PriceLevel:
    """
    Represents aggregate market depth at a specific price level.

    Attributes:
        price: Price level.
        total_quantity: Sum of quantities resting at this price.
        order_count: Number of resting orders at this price.
    """
    price: float
    total_quantity: int
    order_count: int

    def __repr__(self) -> str:
        return f"Level({self.price:.2f} x {self.total_quantity} ({self.order_count} orders))"
