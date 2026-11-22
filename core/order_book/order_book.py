class OrderBook:
    def __init__(self):
        self.buy_orders = []
        self.sell_orders = []

    def add_order(self, order):
        order = order.copy()

        if order["side"] == "BUY":
            self.buy_orders.append(order)
        elif order["side"] == "SELL":
            self.sell_orders.append(order)
        else:
            raise ValueError("Side must be BUY or SELL")

    def get_best_bid(self):
        if not self.buy_orders:
            return None
        return max(order["price"] for order in self.buy_orders)

    def get_best_ask(self):
        if not self.sell_orders:
            return None
        return min(order["price"] for order in self.sell_orders)
