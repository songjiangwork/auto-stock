import pytest

from autostock.ib_client import build_market_order, choose_account, close_order_for_position


def test_choose_account_uses_first_when_preferred_empty() -> None:
    assert choose_account("", ["DU111", "DU222"]) == "DU111"


def test_choose_account_uses_preferred_when_present() -> None:
    assert choose_account("DU222", ["DU111", "DU222"]) == "DU222"


def test_choose_account_raises_when_preferred_not_available() -> None:
    with pytest.raises(RuntimeError):
        choose_account("DU999", ["DU111", "DU222"])


def test_close_order_for_position_long_closes_with_sell() -> None:
    side, qty = close_order_for_position(12.0)
    assert side == "SELL"
    assert qty == 12


def test_close_order_for_position_short_closes_with_buy() -> None:
    side, qty = close_order_for_position(-7.0)
    assert side == "BUY"
    assert qty == 7


def test_close_order_for_position_zero_raises() -> None:
    with pytest.raises(ValueError):
        close_order_for_position(0.0)


def test_build_market_order_sets_day_and_rth_defaults() -> None:
    order = build_market_order("buy", 10)
    assert order.action == "BUY"
    assert order.totalQuantity == 10
    assert order.tif == "DAY"
    assert order.outsideRth is False


def test_build_market_order_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError):
        build_market_order("SELL", 0)
