import pytest

from core.cython_engine.matching_engine import match_quantity


@pytest.mark.parametrize(
    ("buy_quantity", "sell_quantity", "expected"),
    [
        (5, 3, 3),
        (2, 8, 2),
        (4, 4, 4),
        (0, 4, 0),
        (4, 0, 0),
        (-1, 4, 0),
        (4, -1, 0),
    ],
)
def test_match_quantity(buy_quantity, sell_quantity, expected):
    assert match_quantity(buy_quantity, sell_quantity) == expected
