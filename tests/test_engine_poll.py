from __future__ import annotations

from pathlib import Path

from autostock.config import load_config
from autostock.engine import _data_poll_seconds


def _yaml_for_strategy(extra_strategy: str = "") -> str:
    return (
        """\
symbols: [MSFT]
risk:
  max_position_pct: 0.2
  stop_loss_pct: 0.08
  symbol_daily_loss_pct: 0.02
  account_daily_drawdown_pct: 0.05
strategy:
  short_window: 20
  long_window: 50
  bar_size: 10 mins
  duration: 60 D
  loop_interval_seconds: 60
"""
        + extra_strategy
        + """\
ib:
  host: 127.0.0.1
  port: 7497
  client_id: 101
  account: DUXXXXXXX
  trading_mode: paper
"""
    )


def test_data_poll_seconds_auto_uses_half_bar_size() -> None:
    path = Path("data/test_engine_poll_auto.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_for_strategy(), encoding="utf-8")
    cfg = load_config(path)
    assert _data_poll_seconds(cfg) == 300


def test_data_poll_seconds_prefers_explicit_override() -> None:
    path = Path("data/test_engine_poll_explicit.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_yaml_for_strategy("  data_poll_seconds: 420\n"), encoding="utf-8")
    cfg = load_config(path)
    assert _data_poll_seconds(cfg) == 420

