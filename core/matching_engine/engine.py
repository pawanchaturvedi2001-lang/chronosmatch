

from core.cython_engine.matching_engine import match_quantity


class MatchingEngine:
    def __init__(self):
        self.buy_orders = []
        self.sell_orders = []
        self.trades = []

    def process_order(self, order):
        order = order.copy()

        # 1. Validate the order side.
        if order.get("side") not in ("BUY", "SELL"):
            raise ValueError("Side must be BUY or SELL")

        # 2. Validate the quantity.
        if (
            not isinstance(order.get("quantity"), int)
            or isinstance(order.get("quantity"), bool)
            or order["quantity"] <= 0
        ):
            raise ValueError("Quantity must be a positive integer")

        # 3. Validate the price.
        if (
            not isinstance(order.get("price"), (int, float))
            or isinstance(order.get("price"), bool)
            or order["price"] <= 0
        ):
            raise ValueError("Price must be positive")

        # 4. Validate the order ID.
        if "order_id" not in order:
            raise ValueError("Order must contain order_id")

        original_quantity = order["quantity"]
        filled_quantity = 0
        new_trades = []

        # 5. Select opposite-side orders and sort by price.
        # Python's stable sort preserves arrival order for equal prices.
        if order["side"] == "BUY":
            opposite_orders = self.sell_orders

            # Lowest sell price first.
            if len(opposite_orders) > 1:
                opposite_orders.sort(
                    key=lambda resting: resting["price"]
                )
        else:
            opposite_orders = self.buy_orders

            # Highest buy price first.
            if len(opposite_orders) > 1:
                opposite_orders.sort(
                    key=lambda resting: resting["price"],
                    reverse=True,
                )

        index = 0

        # 6. Match the incoming order against existing orders.
        while order["quantity"] > 0 and index < len(opposite_orders):
            resting = opposite_orders[index]

            # Check whether the prices can match.
            if order["side"] == "BUY":
                can_match = resting["price"] <= order["price"]
            else:
                can_match = resting["price"] >= order["price"]

            # Stop if the best available price cannot match.
            if not can_match:
                break

            # Calculate the quantity to trade using Cython.
            traded_quantity = match_quantity(
                order["quantity"],
                resting["quantity"],
            )

            # 7. Create the trade record.
            trade = {
                "buy_order_id": (
                    order["order_id"]
                    if order["side"] == "BUY"
                    else resting["order_id"]
                ),
                "sell_order_id": (
                    order["order_id"]
                    if order["side"] == "SELL"
                    else resting["order_id"]
                ),
                "price": resting["price"],
                "quantity": traded_quantity,
            }

            self.trades.append(trade)
            new_trades.append(trade)

            # 8. Update the quantities.
            order["quantity"] -= traded_quantity
            resting["quantity"] -= traded_quantity
            filled_quantity += traded_quantity

            # Remove completely filled resting orders.
            if resting["quantity"] == 0:
                opposite_orders.pop(index)
            else:
                index += 1

        # 9. Store any remaining quantity in the order book.
        if order["quantity"] > 0:
            if order["side"] == "BUY":
                self.buy_orders.append(order)
            else:
                self.sell_orders.append(order)

        # 10. Return the result.
        return {
            "order_id": order["order_id"],
            "filled_quantity": filled_quantity,
            "remaining_quantity": original_quantity - filled_quantity,
            "trades": new_trades,
        }
