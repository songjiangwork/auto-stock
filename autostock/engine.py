from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime, time as dtime
from zoneinfo import ZoneInfo

from autostock.config import AppConfig
from autostock.database import Database
from autostock.ib_client import IBClient, PositionInfo
from autostock.risk import RiskManager
from autostock.strategy import Signal, evaluate_combined_signal


@dataclass(slots=True)
class EngineContext:
    config: AppConfig
    db: Database
    broker: IBClient
    risk: RiskManager
    shutdown: bool = False


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def us_market_is_open(tz_name: str) -> bool:
    now = now_in_tz(tz_name)
    if now.weekday() > 4:
        return False
    market_open = dtime(9, 30)
    market_close = dtime(16, 0)
    current = now.time()
    return market_open <= current <= market_close


def _today_key(tz_name: str) -> str:
    return now_in_tz(tz_name).date().isoformat()


def _ensure_day_start_equity(ctx: EngineContext, equity: float) -> float:
    day_key = _today_key(ctx.config.timezone)
    key = f"day_start_equity:{day_key}"
    stored = ctx.db.get_state(key)
    if stored is None:
        ctx.db.set_state(key, equity)
        return float(equity)
    return float(stored)


def _symbol_realized_pnl_today(ctx: EngineContext, symbol: str) -> float:
    day_key = _today_key(ctx.config.timezone)
    key = f"symbol_realized:{day_key}:{symbol}"
    return float(ctx.db.get_state(key, 0.0))


def _add_symbol_realized_pnl(ctx: EngineContext, symbol: str, delta: float) -> None:
    day_key = _today_key(ctx.config.timezone)
    key = f"symbol_realized:{day_key}:{symbol}"
    existing = float(ctx.db.get_state(key, 0.0))
    ctx.db.set_state(key, existing + delta)


def _mark_event(ctx: EngineContext, level: str, message: str) -> None:
    ctx.db.log_event(level, message)
    print(f"[{level}] {message}")


def _execute_symbol(ctx: EngineContext, symbol: str, equity: float, positions: dict[str, PositionInfo]) -> None:
    closes = ctx.broker.get_recent_closes(
        symbol=symbol,
        duration=ctx.config.strategy.duration,
        bar_size=ctx.config.strategy.bar_size,
    )
    if not closes:
        _mark_event(ctx, "WARN", f"{symbol}: no historical data")
        return
    last_price = closes[-1]
    signal_, decision_detail = evaluate_combined_signal(
        closes,
        ctx.config.strategy,
        ctx.config.strategy_combo,
    )
    position = positions.get(symbol, PositionInfo(symbol=symbol, quantity=0.0, avg_cost=0.0))
    unrealized = (last_price - position.avg_cost) * position.quantity if position.quantity else 0.0
    ctx.db.record_snapshot(symbol, position.quantity, position.avg_cost, last_price, unrealized)

    if position.quantity > 0 and ctx.risk.stop_loss_triggered(position.avg_cost, last_price):
        qty = int(position.quantity)
        status = ctx.broker.submit_market_order(symbol, "SELL", qty)
        approx_realized = (last_price - position.avg_cost) * qty
        _add_symbol_realized_pnl(ctx, symbol, approx_realized)
        ctx.db.record_order(symbol, "SELL", qty, "STOP_LOSS", status, price=last_price)
        _mark_event(ctx, "INFO", f"{symbol}: stop loss triggered, sold {qty} @ {last_price:.2f}")
        return

    if signal_ == Signal.BUY and position.quantity <= 0:
        day_start = _ensure_day_start_equity(ctx, equity)
        symbol_pnl = _symbol_realized_pnl_today(ctx, symbol)
        decision = ctx.risk.evaluate_entry_guards(equity, day_start, symbol_pnl)
        if not decision.allow_new_position:
            _mark_event(ctx, "WARN", f"{symbol}: entry blocked by risk guard: {decision.reason}")
            return
        qty = ctx.risk.max_shares_for_symbol(equity, last_price)
        if qty <= 0:
            _mark_event(ctx, "WARN", f"{symbol}: computed order quantity is 0")
            return
        status = ctx.broker.submit_market_order(symbol, "BUY", qty)
        ctx.db.record_order(symbol, "BUY", qty, "STRATEGY_BUY", status, price=last_price, note=decision_detail)
        _mark_event(ctx, "INFO", f"{symbol}: BUY {qty} @ {last_price:.2f} ({status}) [{decision_detail}]")
        return

    if signal_ == Signal.SELL and position.quantity > 0:
        qty = int(position.quantity)
        status = ctx.broker.submit_market_order(symbol, "SELL", qty)
        approx_realized = (last_price - position.avg_cost) * qty
        _add_symbol_realized_pnl(ctx, symbol, approx_realized)
        ctx.db.record_order(symbol, "SELL", qty, "STRATEGY_SELL", status, price=last_price, note=decision_detail)
        _mark_event(ctx, "INFO", f"{symbol}: SELL {qty} @ {last_price:.2f} ({status}) [{decision_detail}]")
        return

    _mark_event(ctx, "DEBUG", f"{symbol}: signal={signal_.value}, position={position.quantity}, detail={decision_detail}")


def run_loop(config: AppConfig, db: Database, broker: IBClient, risk: RiskManager) -> None:
    ctx = EngineContext(config=config, db=db, broker=broker, risk=risk)

    def _shutdown_handler(sig: int, _frame: object) -> None:
        del _frame
        ctx.shutdown = True
        _mark_event(ctx, "INFO", f"received signal {sig}, shutting down")

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    _mark_event(ctx, "INFO", "autostock engine started")
    while not ctx.shutdown:
        try:
            if not us_market_is_open(config.timezone):
                _mark_event(ctx, "INFO", "market closed, sleeping")
                time.sleep(config.strategy.loop_interval_seconds)
                continue

            equity = broker.get_equity()
            _ensure_day_start_equity(ctx, equity)
            positions = broker.get_positions()

            for symbol in config.symbols:
                _execute_symbol(ctx, symbol, equity, positions)

        except Exception as exc:  # noqa: BLE001
            _mark_event(ctx, "ERROR", f"loop error: {exc}")
        finally:
            time.sleep(config.strategy.loop_interval_seconds)

    _mark_event(ctx, "INFO", f"engine stopped at {datetime.now(UTC).isoformat()}")
