from core.order_book import OrderBook


def test_best_bid():
    book = OrderBook()
    book.add_order({
        "order_id": 1, "side": "BUY",
        "price": 100, "quantity": 5,
    })
    book.add_order({
        "order_id": 2, "side": "BUY",
        "price": 110, "quantity": 2,
    })
    assert book.get_best_bid() == 110


def test_best_ask():
    book = OrderBook()
    book.add_order({
        "order_id": 1, "side": "SELL",
        "price": 105, "quantity": 3,
    })
    book.add_order({
        "order_id": 2, "side": "SELL",
        "price": 100, "quantity": 2,
    })
    assert book.get_best_ask() == 100


def test_empty_book():
    book = OrderBook()
    assert book.get_best_bid() is None
    assert book.get_best_ask() is None
