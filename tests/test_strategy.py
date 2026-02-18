from autostock.strategy import Signal, moving_average_crossover_signal, simple_moving_average


def test_simple_moving_average_basic() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert simple_moving_average(values, 2) == [1.5, 2.5, 3.5]


def test_moving_average_crossover_buy_signal() -> None:
    closes = [3.0, 2.0, 1.0, 2.0, 3.0]
    assert moving_average_crossover_signal(closes, short_window=2, long_window=3) == Signal.BUY


def test_moving_average_crossover_sell_signal() -> None:
    closes = [1.0, 2.0, 3.0, 2.0, 1.0]
    assert moving_average_crossover_signal(closes, short_window=2, long_window=3) == Signal.SELL


def test_moving_average_crossover_hold_when_not_enough_bars() -> None:
    closes = [1.0, 2.0, 3.0]
    assert moving_average_crossover_signal(closes, short_window=2, long_window=3) == Signal.HOLD
