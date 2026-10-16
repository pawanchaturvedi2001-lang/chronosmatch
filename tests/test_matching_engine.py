
import pytest
from core.matching_engine import MatchingEngine


def test_full_match():
    engine = MatchingEngine()
    engine.process_order({
        "order_id": 1, "side": "SELL",
        "price": 100, "quantity": 5
    })
    result = engine.process_order({
        "order_id": 2, "side": "BUY",
        "price": 100, "quantity": 3
    })
    assert result["filled_quantity"] == 3
    assert result["remaining_quantity"] == 0
    assert len(engine.trades) == 1


def test_partial_match():
    engine = MatchingEngine()
    engine.process_order({
        "order_id": 1, "side": "SELL",
        "price": 100, "quantity": 2
    })
    result = engine.process_order({
        "order_id": 2, "side": "BUY",
        "price": 100, "quantity": 5
    })
    assert result["filled_quantity"] == 2
    assert result["remaining_quantity"] == 3


def test_unmatched_order():
    engine = MatchingEngine()
    result = engine.process_order({
        "order_id": 1, "side": "BUY",
        "price": 90, "quantity": 4
    })
    assert result["filled_quantity"] == 0
    assert result["remaining_quantity"] == 4


def test_invalid_side():
    engine = MatchingEngine()
    with pytest.raises(ValueError):
        engine.process_order({
            "order_id": 1, "side": "HOLD",
            "price": 100, "quantity": 1
        })


def test_invalid_quantity():
    engine = MatchingEngine()
    with pytest.raises(ValueError):
        engine.process_order({
            "order_id": 1, "side": "BUY",
            "price": 100, "quantity": 0
        })


def test_multiple_sells_match_one_buy():
    engine = MatchingEngine()
    engine.process_order({
        "order_id": 1, "side": "SELL",
        "price": 100, "quantity": 2
    })
    engine.process_order({
        "order_id": 2, "side": "SELL",
        "price": 100, "quantity": 3
    })
    result = engine.process_order({
        "order_id": 3, "side": "BUY",
        "price": 100, "quantity": 4
    })
    assert result["filled_quantity"] == 4
    assert result["remaining_quantity"] == 0
    assert len(result["trades"]) == 2


def test_non_matching_prices():
    engine = MatchingEngine()
    engine.process_order({
        "order_id": 1, "side": "SELL",
        "price": 110, "quantity": 2
    })
    result = engine.process_order({
        "order_id": 2, "side": "BUY",
        "price": 100, "quantity": 3
    })
    assert result["filled_quantity"] == 0
    assert result["remaining_quantity"] == 3
    assert len(engine.trades) == 0


def test_invalid_price():
    engine = MatchingEngine()
    with pytest.raises(ValueError):
        engine.process_order({
            "order_id": 1, "side": "BUY",
            "price": -100, "quantity": 2
        })


def test_missing_order_id():
    engine = MatchingEngine()
    with pytest.raises(ValueError):
        engine.process_order({
            "side": "BUY",
            "price": 100, "quantity": 2
        })


def test_price_priority():
    engine = MatchingEngine()

    # Higher-priced sell order arrives first.
    engine.process_order({
        "order_id": 1, "side": "SELL",
        "price": 105, "quantity": 5
    })

    # Lower-priced sell order arrives second.
    engine.process_order({
        "order_id": 2, "side": "SELL",
        "price": 100, "quantity": 3
    })

    result = engine.process_order({
        "order_id": 3, "side": "BUY",
        "price": 105, "quantity": 3
    })

    assert result["filled_quantity"] == 3
    assert result["trades"][0]["sell_order_id"] == 2


def test_time_priority():
    engine = MatchingEngine()

    # First sell order at price 100.
    engine.process_order({
        "order_id": 1, "side": "SELL",
        "price": 100, "quantity": 5
    })

    # Second sell order at the same price.
    engine.process_order({
        "order_id": 2, "side": "SELL",
        "price": 100, "quantity": 3
    })

    result = engine.process_order({
        "order_id": 3, "side": "BUY",
        "price": 100, "quantity": 4
    })

    assert result["filled_quantity"] == 4
    assert result["trades"][0]["sell_order_id"] == 1
    assert result["trades"][0]["quantity"] == 4
