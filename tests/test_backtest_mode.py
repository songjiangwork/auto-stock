from __future__ import annotations

from autostock import backtest as bt
from autostock.config import (
    AppConfig,
    BacktestConfig,
    CapitalConfig,
    IBConfig,
    RiskConfig,
    RSIConfig,
    StrategyComboConfig,
    StrategyConfig,
)
from autostock.ib_client import HistoricalBar
from autostock.strategy import Signal


class _FakeBroker:
    def __init__(self, bars_by_symbol: dict[str, list[HistoricalBar]]) -> None:
        self._bars_by_symbol = bars_by_symbol

    def get_historical_bars(self, symbol: str, duration: str, bar_size: str) -> list[HistoricalBar]:
        del duration, bar_size
        return list(self._bars_by_symbol.get(symbol, []))


def _build_config(mode: str) -> AppConfig:
    return AppConfig(
        symbols=["AAA", "BBB"],
        risk=RiskConfig(
            max_position_pct=1.0,
            stop_loss_pct=0.08,
            symbol_daily_loss_pct=0.02,
            account_daily_drawdown_pct=0.05,
            max_open_positions=10,
            max_consecutive_losses=3,
        ),
        strategy=StrategyConfig(
            short_window=2,
            long_window=3,
            bar_size="5 mins",
            duration="60 D",
            loop_interval_seconds=60,
        ),
        strategy_combo=StrategyComboConfig(
            enabled_strategies=["ma"],
            combination_mode="weighted",
            decision_threshold=0.0,
            weights={"ma": 1.0},
            rsi=RSIConfig(window=14, oversold=30.0, overbought=70.0),
        ),
        capital=CapitalConfig(max_deploy_usd=100.0),
        backtest=BacktestConfig(
            mode=mode,
            slippage_bps=0.0,
            commission_per_order=0.0,
            min_order_notional=0.0,
        ),
        ib=IBConfig(host="127.0.0.1", port=7497, client_id=101, account="DUXXXXXXX", trading_mode="paper"),
        timezone="America/New_York",
        database_path="data/autostock.db",
        log_level="INFO",
    )


def _bars() -> list[HistoricalBar]:
    return [
        HistoricalBar(date="2026-01-01 09:30:00", open=100, high=100, low=100, close=100, volume=1000),
        HistoricalBar(date="2026-01-01 09:35:00", open=100, high=100, low=100, close=100, volume=1000),
        HistoricalBar(date="2026-01-01 09:40:00", open=100, high=100, low=100, close=100, volume=1000),
        HistoricalBar(date="2026-01-01 09:45:00", open=100, high=100, low=100, close=100, volume=1000),
        HistoricalBar(date="2026-01-01 09:50:00", open=100, high=100, low=100, close=100, volume=1000),
    ]


def _fake_eval(closes: list[float], strategy_cfg: StrategyConfig, combo_cfg: StrategyComboConfig) -> tuple[Signal, str]:
    del strategy_cfg, combo_cfg
    if len(closes) == 2:
        return Signal.BUY, "test-buy"
    return Signal.HOLD, "test-hold"


def test_backtest_portfolio_mode_uses_shared_cash_pool(monkeypatch) -> None:
    monkeypatch.setattr(bt, "evaluate_combined_signal", _fake_eval)
    config = _build_config(mode="portfolio")
    broker = _FakeBroker({"AAA": _bars(), "BBB": _bars()})
    results = bt.run_backtest(config, broker, initial_capital=100.0, mode="portfolio")

    by_symbol = {r.symbol: r for r in results}
    assert by_symbol["AAA"].trades == 1
    assert by_symbol["BBB"].trades == 0
    assert sum(r.trades for r in results) == 1


def test_backtest_per_symbol_mode_keeps_independent_cash(monkeypatch) -> None:
    monkeypatch.setattr(bt, "evaluate_combined_signal", _fake_eval)
    config = _build_config(mode="per-symbol")
    broker = _FakeBroker({"AAA": _bars(), "BBB": _bars()})
    results = bt.run_backtest(config, broker, initial_capital=100.0, mode="per-symbol")

    by_symbol = {r.symbol: r for r in results}
    assert by_symbol["AAA"].trades == 1
    assert by_symbol["BBB"].trades == 1
    assert sum(r.trades for r in results) == 2
