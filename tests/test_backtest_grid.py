from __future__ import annotations

from autostock.backtest_grid import (
    apply_overrides,
    generate_grid_overrides,
    grid_scenarios,
    normalize_parameter_grid,
)
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


def _config() -> AppConfig:
    return AppConfig(
        symbols=["MSFT"],
        risk=RiskConfig(
            max_position_pct=0.2,
            stop_loss_pct=0.08,
            symbol_daily_loss_pct=0.02,
            account_daily_drawdown_pct=0.05,
            max_open_positions=5,
            max_consecutive_losses=3,
        ),
        strategy=StrategyConfig(
            short_window=20,
            long_window=50,
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
        capital=CapitalConfig(max_deploy_usd=10000.0),
        backtest=BacktestConfig(
            mode="portfolio",
            slippage_bps=5.0,
            commission_per_order=1.0,
            min_order_notional=100.0,
        ),
        ib=IBConfig(host="127.0.0.1", port=7497, client_id=101, account="DUXXXXXXX", trading_mode="paper"),
        timezone="America/New_York",
        database_path="data/autostock.db",
        log_level="INFO",
    )


def test_generate_grid_overrides_cross_product() -> None:
    grid = normalize_parameter_grid(
        {
            "parameters": {
                "strategy.short_window": [10, 20],
                "strategy.long_window": [50, 80],
            }
        }
    )
    combos = generate_grid_overrides(grid)
    assert len(combos) == 4
    assert {"strategy.short_window": 10, "strategy.long_window": 50} in combos
    assert {"strategy.short_window": 20, "strategy.long_window": 80} in combos


def test_apply_overrides_updates_nested_config_fields() -> None:
    cfg = _config()
    updated = apply_overrides(
        cfg,
        {
            "strategy.short_window": 30,
            "strategy_combo.decision_threshold": 0.6,
        },
    )
    assert updated.strategy.short_window == 30
    assert updated.strategy_combo.decision_threshold == 0.6
    assert cfg.strategy.short_window == 20


def test_grid_scenarios_uses_default_when_missing() -> None:
    scenarios = grid_scenarios({"parameters": {"strategy.short_window": [10]}})
    assert len(scenarios) == 2
    assert scenarios[0]["name"] == "5min"

