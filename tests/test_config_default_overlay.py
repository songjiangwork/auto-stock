from __future__ import annotations

from pathlib import Path

import autostock.config as cfgmod


def test_load_default_config_uses_local_overlay(monkeypatch) -> None:
    base_path = Path("data/test_default_base.yaml")
    local_path = Path("data/test_default_local.yaml")
    base_path.parent.mkdir(parents=True, exist_ok=True)

    base_path.write_text(
        """\
symbols: [AAA, BBB]
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
""",
        encoding="utf-8",
    )
    local_path.write_text(
        """\
symbols: [MSFT]
capital:
  max_deploy_usd: 7777
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(cfgmod, "DEFAULT_BASE_CONFIG", str(base_path))
    monkeypatch.setattr(cfgmod, "DEFAULT_LOCAL_CONFIG", str(local_path))
    cfg = cfgmod.load_default_config()
    assert cfg.symbols == ["MSFT"]
    assert cfg.capital.max_deploy_usd == 7777.0


def test_load_default_config_without_local(monkeypatch) -> None:
    base_path = Path("data/test_default_base_only.yaml")
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text(
        """\
symbols: [SPY]
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
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfgmod, "DEFAULT_BASE_CONFIG", str(base_path))
    monkeypatch.setattr(cfgmod, "DEFAULT_LOCAL_CONFIG", "data/definitely_missing_local.yaml")
    cfg = cfgmod.load_default_config()
    assert cfg.symbols == ["SPY"]
