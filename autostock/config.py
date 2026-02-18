from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RiskConfig:
    max_position_pct: float
    stop_loss_pct: float
    symbol_daily_loss_pct: float
    account_daily_drawdown_pct: float


@dataclass(slots=True)
class StrategyConfig:
    short_window: int
    long_window: int
    bar_size: str
    duration: str
    loop_interval_seconds: int


@dataclass(slots=True)
class IBConfig:
    host: str
    port: int
    client_id: int
    account: str
    trading_mode: str


@dataclass(slots=True)
class AppConfig:
    symbols: list[str]
    risk: RiskConfig
    strategy: StrategyConfig
    ib: IBConfig
    timezone: str
    database_path: str
    log_level: str


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def load_config(path: str | Path) -> AppConfig:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    risk_raw = _require(raw, "risk")
    strategy_raw = _require(raw, "strategy")
    ib_raw = _require(raw, "ib")

    return AppConfig(
        symbols=list(_require(raw, "symbols")),
        risk=RiskConfig(
            max_position_pct=float(_require(risk_raw, "max_position_pct")),
            stop_loss_pct=float(_require(risk_raw, "stop_loss_pct")),
            symbol_daily_loss_pct=float(_require(risk_raw, "symbol_daily_loss_pct")),
            account_daily_drawdown_pct=float(_require(risk_raw, "account_daily_drawdown_pct")),
        ),
        strategy=StrategyConfig(
            short_window=int(_require(strategy_raw, "short_window")),
            long_window=int(_require(strategy_raw, "long_window")),
            bar_size=str(_require(strategy_raw, "bar_size")),
            duration=str(_require(strategy_raw, "duration")),
            loop_interval_seconds=int(_require(strategy_raw, "loop_interval_seconds")),
        ),
        ib=IBConfig(
            host=str(_require(ib_raw, "host")),
            port=int(_require(ib_raw, "port")),
            client_id=int(_require(ib_raw, "client_id")),
            account=str(_require(ib_raw, "account")),
            trading_mode=str(_require(ib_raw, "trading_mode")),
        ),
        timezone=str(raw.get("timezone", "America/New_York")),
        database_path=str(raw.get("database_path", "data/autostock.db")),
        log_level=str(raw.get("log_level", "INFO")),
    )
