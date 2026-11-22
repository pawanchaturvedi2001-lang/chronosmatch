
import json
import os
from datetime import datetime


class TradeWriter:
    def __init__(self, file_path="trades.jsonl"):
        self.file_path = file_path

        # Create the directory if it does not exist
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def write_trade(self, trade):
        """
        Save one executed trade to a JSON Lines file.
        """

        if not isinstance(trade, dict):
            raise TypeError("Trade must be a dictionary")

        required_fields = ["buy_order_id", "sell_order_id", "price", "quantity"]

        for field in required_fields:
            if field not in trade:
                raise ValueError(f"Missing trade field: {field}")

        price = trade["price"]
        quantity = trade["quantity"]

        if not isinstance(price, (int, float)) or price <= 0:
            raise ValueError("Trade price must be positive")

        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("Trade quantity must be a positive integer")

        trade_record = {
            "buy_order_id": trade["buy_order_id"],
            "sell_order_id": trade["sell_order_id"],
            "price": price,
            "quantity": quantity,
            "timestamp": datetime.now().isoformat()
        }

        with open(self.file_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(trade_record) + "\n")

        return trade_record

    def read_trades(self):
        """Read all previously recorded trades."""

        if not os.path.exists(self.file_path):
            return []

        trades = []

        with open(self.file_path, "r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    trades.append(json.loads(line))

        return trades
