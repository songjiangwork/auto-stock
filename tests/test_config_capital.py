from __future__ import annotations

from pathlib import Path

from autostock.config import load_config


def _base_yaml() -> str:
    return """\
symbols: [MSFT]
risk:
  max_position_pct: 0.2
  stop_loss_pct: 0.08
  symbol_daily_loss_pct: 0.02
  account_daily_drawdown_pct: 0.05
strategy:
  short_window: 20
  long_window: 50
  bar_size: 5 mins
  duration: 60 D
  loop_interval_seconds: 60
ib:
  host: 127.0.0.1
  port: 7497
  client_id: 101
  account: DUXXXXXXX
  trading_mode: paper
"""


def test_capital_defaults_to_10000_when_missing() -> None:
    path = Path("data/test_config_capital_default.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_base_yaml(), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.capital.max_deploy_usd == 10000.0
    assert cfg.strategy.data_poll_seconds is None
    assert cfg.strategy.incremental_duration == "3 D"
    assert cfg.strategy.cache_max_bars == 10000


def test_capital_uses_explicit_value() -> None:
    path = Path("data/test_config_capital_explicit.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_base_yaml() + "\ncapital:\n  max_deploy_usd: 5000\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.capital.max_deploy_usd == 5000.0


def test_strategy_cache_fields_use_explicit_values() -> None:
    path = Path("data/test_config_strategy_cache_fields.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _base_yaml()
        + "\nstrategy:\n  short_window: 20\n  long_window: 50\n  bar_size: 5 mins\n  duration: 60 D\n  loop_interval_seconds: 60\n  incremental_duration: 2 D\n  cache_max_bars: 6000\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.strategy.incremental_duration == "2 D"
    assert cfg.strategy.cache_max_bars == 6000


def test_strategy_data_poll_seconds_uses_explicit_positive_value() -> None:
    path = Path("data/test_config_strategy_data_poll.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _base_yaml()
        + "\nstrategy:\n  short_window: 20\n  long_window: 50\n  bar_size: 5 mins\n  duration: 60 D\n  loop_interval_seconds: 60\n  data_poll_seconds: 240\n",
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.strategy.data_poll_seconds == 240
