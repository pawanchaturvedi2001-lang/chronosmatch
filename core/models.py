"""
ChronosMatch Core Models
Trade representation and Level 2 Price Level data structures.
Reuses the binary Order and Side representations from ipc.structures.
"""

from dataclasses import dataclass
import time
from typing import Dict, Any, List, Optional

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


@dataclass(slots=True)
class WhaleSweep:
    """
    Represents a multi-level liquidity sweep event triggered by a single order.

    Attributes:
        order_id: Order ID that initiated the sweep.
        side: Order side ('BUY' or 'SELL').
        levels_swept: Number of distinct price levels consumed.
        total_quantity: Total volume executed across all swept levels.
        start_price: First execution price.
        end_price: Final execution price.
        trades_count: Number of individual fill trades generated.
        trades: List of Trade objects belonging to this sweep.
        residual_quantity: Any remaining quantity of the incoming order.
        timestamp_ns: Nanosecond timestamp of the sweep.
    """
    order_id: int
    side: str
    levels_swept: int
    total_quantity: int
    start_price: float
    end_price: float
    trades_count: int
    trades: List[Trade]
    residual_quantity: int = 0
    timestamp_ns: int = 0

    def __post_init__(self):
        if self.timestamp_ns == 0:
            object.__setattr__(self, "timestamp_ns", time.time_ns())

    def to_dict(self) -> Dict[str, Any]:
        """Convert sweep event to a dictionary representation."""
        return {
            "order_id": self.order_id,
            "side": self.side,
            "levels_swept": self.levels_swept,
            "total_quantity": self.total_quantity,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "trades_count": self.trades_count,
            "residual_quantity": self.residual_quantity,
            "timestamp_ns": self.timestamp_ns,
            "trades": [t.to_dict() for t in self.trades],
        }

    def summary_str(self) -> str:
        """Formatted human-readable summary of the sweep."""
        res_str = f" (rest: {self.residual_quantity})" if self.residual_quantity > 0 else " (full fill)"
        return (
            f"WHALE SWEEP #{self.order_id} ({self.side}): {self.levels_swept} levels swept, "
            f"{self.total_quantity:,} shares @ {self.start_price:.2f}->{self.end_price:.2f}{res_str}"
        )

    def __repr__(self) -> str:
        return self.summary_str()

