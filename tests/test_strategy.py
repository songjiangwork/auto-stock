from autostock.config import RSIConfig, StrategyComboConfig, StrategyConfig
from autostock.strategy import (
    Signal,
    evaluate_combined_signal,
    moving_average_crossover_signal,
    rsi_signal,
    simple_moving_average,
)


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


def test_rsi_signal_buy_when_oversold() -> None:
    closes = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1, 1, 1, 1, 1]
    cfg = RSIConfig(window=14, oversold=30.0, overbought=70.0)
    assert rsi_signal(closes, cfg) == Signal.BUY


def test_combined_signal_weighted_with_ma_and_rsi() -> None:
    closes = [3.0, 2.0, 1.0, 2.0, 3.0]
    strategy_cfg = StrategyConfig(short_window=2, long_window=3, bar_size="5 mins", duration="60 D", loop_interval_seconds=60)
    combo_cfg = StrategyComboConfig(
        enabled_strategies=["ma", "rsi"],
        combination_mode="weighted",
        decision_threshold=0.2,
        weights={"ma": 0.7, "rsi": 0.3},
        rsi=RSIConfig(window=2, oversold=40.0, overbought=60.0),
    )
    signal, detail = evaluate_combined_signal(closes, strategy_cfg, combo_cfg)
    assert signal in {Signal.BUY, Signal.HOLD, Signal.SELL}
    assert "weighted" in detail
