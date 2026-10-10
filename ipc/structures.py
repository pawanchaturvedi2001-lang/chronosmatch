"""
ChronosMatch Zero-Copy High-Frequency Trading Engine
IPC Structures module (Member 1)

Defines binary structures and serialization for zero-copy IPC orders.
"""

from dataclasses import dataclass
from enum import IntEnum
import struct
import time


class Side(IntEnum):
    """Order side: BUY or SELL."""
    BUY = 1
    SELL = 2


SIDE_BUY = Side.BUY
SIDE_SELL = Side.SELL

# Binary layout for fixed-size zero-copy Order:
# '<QdIBQ' (29 bytes, little-endian, no padding):
#   Q: uint64  order_id     (8 bytes)
#   d: double  price        (8 bytes)
#   I: uint32  quantity     (4 bytes)
#   B: uint8   side (1/2)   (1 byte)
#   Q: uint64  timestamp_ns (8 bytes)
ORDER_FORMAT = "<QdIBQ"
ORDER_STRUCT = struct.Struct(ORDER_FORMAT)
ORDER_SIZE = ORDER_STRUCT.size  # 29 bytes


@dataclass(slots=True)
class Order:
    """
    Fixed-size Order entity for high-frequency trading.

    Attributes:
        order_id: Unique 64-bit integer ID.
        price: Order limit price (double).
        quantity: Order quantity / shares (32-bit unsigned integer).
        side: Side.BUY (1) or Side.SELL (2), or string 'BUY'/'SELL'.
        timestamp_ns: Nanosecond timestamp (defaults to current time if 0).
    """
    order_id: int
    price: float
    quantity: int
    side: int
    timestamp_ns: int = 0

    def __post_init__(self):
        # Convert string side representation if passed
        if isinstance(self.side, str):
            s = self.side.strip().upper()
            if s in ("BUY", "B", "1"):
                object.__setattr__(self, "side", int(Side.BUY))
            elif s in ("SELL", "S", "2"):
                object.__setattr__(self, "side", int(Side.SELL))
            else:
                raise ValueError(f"Invalid order side: {self.side}. Must be BUY or SELL.")
        else:
            object.__setattr__(self, "side", int(self.side))

        if self.timestamp_ns == 0:
            object.__setattr__(self, "timestamp_ns", time.time_ns())

    @property
    def side_name(self) -> str:
        """Returns string side: 'BUY' or 'SELL'."""
        return "BUY" if self.side == Side.BUY else "SELL"

    def __repr__(self) -> str:
        return (
            f"Order({self.side_name} id={self.order_id} @ {self.price:.2f} "
            f"qty={self.quantity} ts={self.timestamp_ns})"
        )


def pack_order(order: Order) -> bytes:
    """
    Serialize an Order into a compact 29-byte binary representation.

    Args:
        order: The Order dataclass instance.

    Returns:
        29 bytes of packed binary data.
    """
    return ORDER_STRUCT.pack(
        order.order_id,
        float(order.price),
        int(order.quantity),
        int(order.side),
        int(order.timestamp_ns),
    )


def unpack_order(data: bytes) -> Order:
    """
    Deserialize a 29-byte binary buffer back into an Order dataclass instance.

    Args:
        data: At least 29 bytes of packed order data.

    Returns:
        Order instance with unpacked fields.
    """
    order_id, price, quantity, side, timestamp_ns = ORDER_STRUCT.unpack(data[:ORDER_SIZE])
    return Order(
        order_id=order_id,
        price=price,
        quantity=quantity,
        side=side,
        timestamp_ns=timestamp_ns,
    )

