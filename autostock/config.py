from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BASE_CONFIG = "config/config.yaml"
DEFAULT_LOCAL_CONFIG = "config/config.local.yaml"


@dataclass(slots=True)
class RiskConfig:
    max_position_pct: float
    stop_loss_pct: float
    symbol_daily_loss_pct: float
    account_daily_drawdown_pct: float
    max_open_positions: int = 10
    max_consecutive_losses: int = 3


@dataclass(slots=True)
class StrategyConfig:
    short_window: int
    long_window: int
    bar_size: str
    duration: str
    loop_interval_seconds: int


@dataclass(slots=True)
class RSIConfig:
    window: int
    oversold: float
    overbought: float


@dataclass(slots=True)
class StrategyComboConfig:
    enabled_strategies: list[str]
    combination_mode: str
    decision_threshold: float
    weights: dict[str, float]
    rsi: RSIConfig


@dataclass(slots=True)
class CapitalConfig:
    max_deploy_usd: float


@dataclass(slots=True)
class BacktestConfig:
    mode: str
    slippage_bps: float
    commission_per_order: float
    min_order_notional: float


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
    strategy_combo: StrategyComboConfig
    capital: CapitalConfig
    backtest: BacktestConfig
    ib: IBConfig
    timezone: str
    database_path: str
    log_level: str


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"Missing required config key: {key}")
    return data[key]


def _load_yaml(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path) -> AppConfig:
    raw = _load_yaml(path)

    risk_raw = _require(raw, "risk")
    strategy_raw = _require(raw, "strategy")
    ib_raw = _require(raw, "ib")
    combo_raw = dict(raw.get("strategy_combo", {}))
    rsi_raw = dict(combo_raw.get("rsi", {}))
    capital_raw = dict(raw.get("capital", {}))
    backtest_raw = dict(raw.get("backtest", {}))

    return AppConfig(
        symbols=list(_require(raw, "symbols")),
        risk=RiskConfig(
            max_position_pct=float(_require(risk_raw, "max_position_pct")),
            stop_loss_pct=float(_require(risk_raw, "stop_loss_pct")),
            symbol_daily_loss_pct=float(_require(risk_raw, "symbol_daily_loss_pct")),
            account_daily_drawdown_pct=float(_require(risk_raw, "account_daily_drawdown_pct")),
            max_open_positions=int(risk_raw.get("max_open_positions", 10)),
            max_consecutive_losses=int(risk_raw.get("max_consecutive_losses", 3)),
        ),
        strategy=StrategyConfig(
            short_window=int(_require(strategy_raw, "short_window")),
            long_window=int(_require(strategy_raw, "long_window")),
            bar_size=str(_require(strategy_raw, "bar_size")),
            duration=str(_require(strategy_raw, "duration")),
            loop_interval_seconds=int(_require(strategy_raw, "loop_interval_seconds")),
        ),
        strategy_combo=StrategyComboConfig(
            enabled_strategies=[str(x).lower() for x in combo_raw.get("enabled_strategies", ["ma"])],
            combination_mode=str(combo_raw.get("combination_mode", "weighted")).lower(),
            decision_threshold=float(combo_raw.get("decision_threshold", 0.0)),
            weights={str(k).lower(): float(v) for k, v in dict(combo_raw.get("weights", {"ma": 1.0})).items()},
            rsi=RSIConfig(
                window=int(rsi_raw.get("window", 14)),
                oversold=float(rsi_raw.get("oversold", 30.0)),
                overbought=float(rsi_raw.get("overbought", 70.0)),
            ),
        ),
        capital=CapitalConfig(
            max_deploy_usd=float(capital_raw.get("max_deploy_usd", 10000.0)),
        ),
        backtest=BacktestConfig(
            mode=str(backtest_raw.get("mode", "portfolio")).lower(),
            slippage_bps=float(backtest_raw.get("slippage_bps", 5.0)),
            commission_per_order=float(backtest_raw.get("commission_per_order", 1.0)),
            min_order_notional=float(backtest_raw.get("min_order_notional", 100.0)),
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


def load_default_config() -> AppConfig:
    base_path = Path(DEFAULT_BASE_CONFIG)
    local_path = Path(DEFAULT_LOCAL_CONFIG)
    raw = _load_yaml(base_path)
    if local_path.exists():
        raw = _deep_merge(raw, _load_yaml(local_path))

    risk_raw = _require(raw, "risk")
    strategy_raw = _require(raw, "strategy")
    ib_raw = _require(raw, "ib")
    combo_raw = dict(raw.get("strategy_combo", {}))
    rsi_raw = dict(combo_raw.get("rsi", {}))
    capital_raw = dict(raw.get("capital", {}))
    backtest_raw = dict(raw.get("backtest", {}))

    return AppConfig(
        symbols=list(_require(raw, "symbols")),
        risk=RiskConfig(
            max_position_pct=float(_require(risk_raw, "max_position_pct")),
            stop_loss_pct=float(_require(risk_raw, "stop_loss_pct")),
            symbol_daily_loss_pct=float(_require(risk_raw, "symbol_daily_loss_pct")),
            account_daily_drawdown_pct=float(_require(risk_raw, "account_daily_drawdown_pct")),
            max_open_positions=int(risk_raw.get("max_open_positions", 10)),
            max_consecutive_losses=int(risk_raw.get("max_consecutive_losses", 3)),
        ),
        strategy=StrategyConfig(
            short_window=int(_require(strategy_raw, "short_window")),
            long_window=int(_require(strategy_raw, "long_window")),
            bar_size=str(_require(strategy_raw, "bar_size")),
            duration=str(_require(strategy_raw, "duration")),
            loop_interval_seconds=int(_require(strategy_raw, "loop_interval_seconds")),
        ),
        strategy_combo=StrategyComboConfig(
            enabled_strategies=[str(x).lower() for x in combo_raw.get("enabled_strategies", ["ma"])],
            combination_mode=str(combo_raw.get("combination_mode", "weighted")).lower(),
            decision_threshold=float(combo_raw.get("decision_threshold", 0.0)),
            weights={str(k).lower(): float(v) for k, v in dict(combo_raw.get("weights", {"ma": 1.0})).items()},
            rsi=RSIConfig(
                window=int(rsi_raw.get("window", 14)),
                oversold=float(rsi_raw.get("oversold", 30.0)),
                overbought=float(rsi_raw.get("overbought", 70.0)),
            ),
        ),
        capital=CapitalConfig(
            max_deploy_usd=float(capital_raw.get("max_deploy_usd", 10000.0)),
        ),
        backtest=BacktestConfig(
            mode=str(backtest_raw.get("mode", "portfolio")).lower(),
            slippage_bps=float(backtest_raw.get("slippage_bps", 5.0)),
            commission_per_order=float(backtest_raw.get("commission_per_order", 1.0)),
            min_order_notional=float(backtest_raw.get("min_order_notional", 100.0)),
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
