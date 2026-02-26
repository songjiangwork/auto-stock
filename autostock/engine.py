from __future__ import annotations

import queue
import signal
import asyncio
import threading
import time
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from autostock.config import AppConfig, IBConfig
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


@dataclass(slots=True)
class MarketDataUpdate:
    symbol: str
    closes: list[float]
    last_bar_key: str


def _merge_cached_bars(
    existing: list[tuple[str, float]],
    fetched: list[tuple[str, float]],
    max_bars: int,
) -> list[tuple[str, float]]:
    if not existing:
        out = list(fetched)
    else:
        merged: dict[str, float] = {date: close for date, close in existing}
        for date, close in fetched:
            merged[date] = close
        out = list(merged.items())
    if len(out) > max_bars:
        out = out[-max_bars:]
    return out


def _safe_cache_token(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return out.strip("_") or "default"


def _parse_bar_datetime(value: str, tz_name: str) -> datetime | None:
    raw = str(value).strip()
    if not raw:
        return None
    candidates = [
        raw,
        raw.replace("  ", " "),
    ]
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
            return dt
        except ValueError:
            pass
        for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
            try:
                dt = datetime.strptime(candidate, fmt)
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
                return dt
            except ValueError:
                continue
    return None


def _bar_size_seconds(bar_size: str) -> int:
    text = bar_size.strip().lower()
    parts = text.split()
    if len(parts) < 2:
        return 60
    try:
        num = max(1, int(parts[0]))
    except ValueError:
        return 60
    unit = parts[1]
    if unit.startswith("sec"):
        return num
    if unit.startswith("min"):
        return num * 60
    if unit.startswith("hour"):
        return num * 3600
    if unit.startswith("day"):
        return num * 86400
    return 60


def _seconds_to_ib_duration(total_seconds: float) -> str:
    seconds = max(60, int(total_seconds))
    if seconds < 86400:
        return f"{seconds} S"
    days = (seconds + 86399) // 86400
    return f"{days} D"


def _ib_duration_to_seconds(duration: str) -> int:
    parts = duration.strip().upper().split()
    if len(parts) != 2:
        raise ValueError(f"invalid IB duration: {duration}")
    value = int(parts[0])
    unit = parts[1]
    if unit == "S":
        return value
    if unit == "D":
        return value * 86400
    if unit == "W":
        return value * 7 * 86400
    if unit == "M":
        return value * 30 * 86400
    if unit == "Y":
        return value * 365 * 86400
    raise ValueError(f"invalid IB duration unit: {duration}")


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


def _set_symbol_realized_pnl_today(ctx: EngineContext, symbol: str, value: float) -> None:
    day_key = _today_key(ctx.config.timezone)
    key = f"symbol_realized:{day_key}:{symbol}"
    ctx.db.set_state(key, float(value))


def _mark_event(ctx: EngineContext, level: str, message: str) -> None:
    ctx.db.log_event(level, message)
    ts = now_in_tz(ctx.config.timezone).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{level}] [{ts}] {message}")


def _print_runtime_log(level: str, message: str, tz_name: str) -> None:
    ts = now_in_tz(tz_name).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{level}] [{ts}] {message}")


def _sleep_interruptible(ctx: EngineContext, seconds: float) -> None:
    remaining = max(0.0, float(seconds))
    while remaining > 0 and not ctx.shutdown:
        chunk = 1.0 if remaining > 1.0 else remaining
        time.sleep(chunk)
        remaining -= chunk


def _sleep_with_stop(stop_event: threading.Event, seconds: float) -> None:
    remaining = max(0.0, float(seconds))
    while remaining > 0 and not stop_event.is_set():
        chunk = 1.0 if remaining > 1.0 else remaining
        time.sleep(chunk)
        remaining -= chunk


def _data_poll_seconds(config: AppConfig) -> int:
    explicit = config.strategy.data_poll_seconds
    if explicit is not None:
        return max(15, int(explicit))
    bar_seconds = _bar_size_seconds(config.strategy.bar_size)
    return max(15, bar_seconds // 2)


class MarketDataFeed:
    def __init__(self, config: AppConfig, symbols: list[str], ib_cfg: IBConfig) -> None:
        self.config = config
        self.symbols = list(symbols)
        self.ib_cfg = ib_cfg
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.update_queue: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.latest: dict[str, MarketDataUpdate] = {}
        self.last_seen_key: dict[str, str] = {}
        self.poll_seconds = _data_poll_seconds(config)
        self.cache_dir = Path("data") / "cache" / "market_data"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cached_bars: dict[str, list[tuple[str, float]]] = {}
        for symbol in self.symbols:
            self.cached_bars[symbol] = self._load_symbol_cache(symbol)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="market-data-feed", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5.0)

    def next_symbol(self, timeout_seconds: float = 1.0) -> str | None:
        try:
            return self.update_queue.get(timeout=max(0.01, timeout_seconds))
        except queue.Empty:
            return None

    def get_latest(self, symbol: str) -> MarketDataUpdate | None:
        with self.lock:
            return self.latest.get(symbol)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        broker: IBClient | None = None
        _print_runtime_log("INFO", f"market data feed started (poll={self.poll_seconds}s)", self.config.timezone)
        try:
            broker = IBClient(self.ib_cfg)
            broker.connect()
            broker.ensure_symbols(self.symbols)
            while not self.stop_event.is_set():
                try:
                    if not us_market_is_open(self.config.timezone):
                        _sleep_with_stop(self.stop_event, self.poll_seconds)
                        continue
                    for symbol in self.symbols:
                        if self.stop_event.is_set():
                            break
                        existing_pairs = self.cached_bars.get(symbol, [])
                        duration = self._next_duration(symbol, existing_pairs)
                        fetch_start = time.perf_counter()
                        bars = broker.get_historical_bars(
                            symbol=symbol,
                            duration=duration,
                            bar_size=self.config.strategy.bar_size,
                        )
                        fetch_elapsed = time.perf_counter() - fetch_start
                        _print_runtime_log(
                            "DEBUG",
                            (
                                f"{symbol}: data_fetch_elapsed={fetch_elapsed:.3f}s duration={duration} "
                                f"fetched_bars={len(bars)} cached_bars={len(existing_pairs)}"
                            ),
                            self.config.timezone,
                        )
                        if not bars:
                            continue
                        fetched_pairs = [(str(bar.date), float(bar.close)) for bar in bars]
                        merged_pairs = _merge_cached_bars(
                            existing_pairs,
                            fetched_pairs,
                            max_bars=self.config.strategy.cache_max_bars,
                        )
                        self.cached_bars[symbol] = merged_pairs
                        self._save_symbol_cache(symbol, merged_pairs)
                        closes = [close for _date, close in merged_pairs]
                        last_date = merged_pairs[-1][0]
                        last_close = merged_pairs[-1][1]
                        last_bar_key = f"{last_date}|{last_close:.6f}|{len(closes)}"
                        if self.last_seen_key.get(symbol) == last_bar_key:
                            continue
                        self.last_seen_key[symbol] = last_bar_key
                        update = MarketDataUpdate(symbol=symbol, closes=closes, last_bar_key=last_bar_key)
                        with self.lock:
                            self.latest[symbol] = update
                        self.update_queue.put(symbol)
                except Exception as exc:  # noqa: BLE001
                    _print_runtime_log("WARN", f"market data feed error: {exc}", self.config.timezone)
                finally:
                    _sleep_with_stop(self.stop_event, self.poll_seconds)
        except Exception as exc:  # noqa: BLE001
            _print_runtime_log("WARN", f"market data feed setup failed: {exc}", self.config.timezone)
        finally:
            if broker is not None:
                broker.disconnect()
            loop.close()
        _print_runtime_log("INFO", "market data feed stopped", self.config.timezone)

    def _cache_file(self, symbol: str) -> Path:
        bar_key = _safe_cache_token(self.config.strategy.bar_size)
        duration_key = _safe_cache_token(self.config.strategy.duration)
        return self.cache_dir / f"{symbol.upper()}__{bar_key}__{duration_key}.json"

    def _next_duration(self, symbol: str, existing_pairs: list[tuple[str, float]]) -> str:
        if not existing_pairs:
            return self.config.strategy.duration
        last_dt = _parse_bar_datetime(existing_pairs[-1][0], self.config.timezone)
        if last_dt is None:
            return self.config.strategy.incremental_duration
        now_dt = now_in_tz(self.config.timezone)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=now_dt.tzinfo)
        gap_seconds = max(0.0, (now_dt - last_dt).total_seconds())
        bar_seconds = _bar_size_seconds(self.config.strategy.bar_size)
        # pull at least two bars of overlap to avoid timestamp boundary gaps.
        required_seconds = max(gap_seconds + (bar_seconds * 2), bar_seconds * 2)
        dynamic_duration = _seconds_to_ib_duration(required_seconds)
        # if configured incremental duration is larger, honor it.
        configured_floor = self.config.strategy.incremental_duration
        try:
            floor_seconds = _ib_duration_to_seconds(configured_floor)
            if floor_seconds > required_seconds:
                return configured_floor
        except ValueError:
            return configured_floor
        return dynamic_duration

    def _load_symbol_cache(self, symbol: str) -> list[tuple[str, float]]:
        path = self._cache_file(symbol)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            bars = raw.get("bars", [])
            out: list[tuple[str, float]] = []
            for item in bars:
                if not isinstance(item, list) or len(item) != 2:
                    continue
                out.append((str(item[0]), float(item[1])))
            if len(out) > self.config.strategy.cache_max_bars:
                out = out[-self.config.strategy.cache_max_bars :]
            return out
        except Exception:  # noqa: BLE001
            return []

    def _save_symbol_cache(self, symbol: str, bars: list[tuple[str, float]]) -> None:
        path = self._cache_file(symbol)
        payload = {
            "symbol": symbol.upper(),
            "bar_size": self.config.strategy.bar_size,
            "duration": self.config.strategy.duration,
            "bars": [[d, c] for d, c in bars],
        }
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


def _effective_equity(ctx: EngineContext, ib_equity: float) -> float:
    cap = max(0.0, ctx.config.capital.max_deploy_usd)
    if cap <= 0:
        return ib_equity
    return min(ib_equity, cap)


def _consecutive_losses_today(ctx: EngineContext) -> int:
    day_key = _today_key(ctx.config.timezone)
    return int(ctx.db.get_state(f"consecutive_losses:{day_key}", 0))


def _set_consecutive_losses_today(ctx: EngineContext, value: int) -> None:
    day_key = _today_key(ctx.config.timezone)
    ctx.db.set_state(f"consecutive_losses:{day_key}", int(max(0, value)))


def _update_consecutive_losses_after_exit(ctx: EngineContext, realized_pnl: float) -> None:
    current = _consecutive_losses_today(ctx)
    if realized_pnl < 0:
        _set_consecutive_losses_today(ctx, current + 1)
    else:
        _set_consecutive_losses_today(ctx, 0)


def _startup_sync(ctx: EngineContext) -> None:
    last_sync = ctx.db.latest_execution_ts()
    executions = ctx.broker.get_executions_since(last_sync)
    new_count = 0
    for exe in executions:
        ctx.db.upsert_execution(
            exec_id=exe.exec_id,
            ts_utc=exe.ts_utc,
            account=exe.account,
            symbol=exe.symbol,
            side=exe.side,
            quantity=exe.quantity,
            price=exe.price,
            order_id=exe.order_id,
            perm_id=exe.perm_id,
        )
        new_count += 1

    symbol_pnl, consecutive_losses = ctx.db.rebuild_daily_risk_state(ctx.config.timezone)
    day_key = _today_key(ctx.config.timezone)
    ctx.db.delete_state_prefix(f"symbol_realized:{day_key}:")
    for symbol, pnl in symbol_pnl.items():
        _set_symbol_realized_pnl_today(ctx, symbol, pnl)
    _set_consecutive_losses_today(ctx, consecutive_losses)

    positions = ctx.broker.get_positions()
    position_symbols = sorted(symbol for symbol, p in positions.items() if p.quantity > 0)
    _mark_event(
        ctx,
        "INFO",
        (
            f"startup sync completed: executions_fetched={new_count}, "
            f"open_positions={len(position_symbols)}, consecutive_losses_today={consecutive_losses}"
        ),
    )


def _execute_symbol(ctx: EngineContext, symbol: str, equity: float, positions: dict[str, PositionInfo], closes: list[float]) -> None:
    process_start = time.perf_counter()
    if not closes:
        _mark_event(ctx, "WARN", f"{symbol}: no historical data")
        return
    last_price = closes[-1]
    analysis_start = time.perf_counter()
    signal_, decision_detail = evaluate_combined_signal(
        closes,
        ctx.config.strategy,
        ctx.config.strategy_combo,
    )
    analysis_elapsed = time.perf_counter() - analysis_start
    _mark_event(ctx, "DEBUG", f"{symbol}: analysis_elapsed={analysis_elapsed:.3f}s bars={len(closes)}")
    position = positions.get(symbol, PositionInfo(symbol=symbol, quantity=0.0, avg_cost=0.0))
    if signal_ in {Signal.BUY, Signal.SELL}:
        _mark_event(
            ctx,
            "INFO",
            (
                f"\n==============\n{symbol}: analysis_signal={signal_.value}, "
                f"price={last_price:.2f}, position={position.quantity}, detail={decision_detail}\n==============\n"
            ),
        )
    unrealized = (last_price - position.avg_cost) * position.quantity if position.quantity else 0.0
    ctx.db.record_snapshot(symbol, position.quantity, position.avg_cost, last_price, unrealized)

    if position.quantity > 0 and ctx.risk.stop_loss_triggered(position.avg_cost, last_price):
        qty = int(position.quantity)
        status = ctx.broker.submit_market_order(symbol, "SELL", qty)
        approx_realized = (last_price - position.avg_cost) * qty
        _update_consecutive_losses_after_exit(ctx, approx_realized)
        _add_symbol_realized_pnl(ctx, symbol, approx_realized)
        ctx.db.record_order(symbol, "SELL", qty, "STOP_LOSS", status, price=last_price)
        _mark_event(ctx, "INFO", f"{symbol}: stop loss triggered, sold {qty} @ {last_price:.2f}")
        return

    if signal_ == Signal.BUY and position.quantity <= 0:
        day_start = _ensure_day_start_equity(ctx, equity)
        symbol_pnl = _symbol_realized_pnl_today(ctx, symbol)
        open_positions = sum(1 for p in positions.values() if p.quantity > 0)
        consecutive_losses = _consecutive_losses_today(ctx)
        decision = ctx.risk.evaluate_entry_guards(
            equity,
            day_start,
            symbol_pnl,
            open_positions=open_positions,
            consecutive_losses=consecutive_losses,
        )
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
        _mark_event(ctx, "DEBUG", f"{symbol}: process_elapsed={time.perf_counter() - process_start:.3f}s")
        return

    if signal_ == Signal.SELL and position.quantity > 0:
        qty = int(position.quantity)
        status = ctx.broker.submit_market_order(symbol, "SELL", qty)
        approx_realized = (last_price - position.avg_cost) * qty
        _update_consecutive_losses_after_exit(ctx, approx_realized)
        _add_symbol_realized_pnl(ctx, symbol, approx_realized)
        ctx.db.record_order(symbol, "SELL", qty, "STRATEGY_SELL", status, price=last_price, note=decision_detail)
        _mark_event(ctx, "INFO", f"{symbol}: SELL {qty} @ {last_price:.2f} ({status}) [{decision_detail}]")
        _mark_event(ctx, "DEBUG", f"{symbol}: process_elapsed={time.perf_counter() - process_start:.3f}s")
        return

    _mark_event(ctx, "DEBUG", f"{symbol}: signal={signal_.value}, position={position.quantity}, detail={decision_detail}")
    _mark_event(ctx, "DEBUG", f"{symbol}: process_elapsed={time.perf_counter() - process_start:.3f}s")


def run_loop(config: AppConfig, db: Database, broker: IBClient, risk: RiskManager) -> None:
    ctx = EngineContext(config=config, db=db, broker=broker, risk=risk)
    data_feed: MarketDataFeed | None = None

    def _shutdown_handler(sig: int, _frame: object) -> None:
        del _frame
        ctx.shutdown = True
        _mark_event(ctx, "INFO", f"received signal {sig}, shutting down")
        _mark_event(ctx, "INFO", "shutdown requested: finishing current symbol operation, then exiting")

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    _mark_event(ctx, "INFO", "autostock engine started")
    _startup_sync(ctx)
    data_cfg = replace(config.ib, client_id=config.ib.client_id + 2)
    data_feed = MarketDataFeed(config, config.symbols, data_cfg)
    data_feed.start()

    warned_cap = False
    while not ctx.shutdown:
        try:
            if not us_market_is_open(config.timezone):
                _mark_event(ctx, "INFO", "market closed, sleeping")
                _sleep_interruptible(ctx, 5.0)
                continue

            ib_equity = broker.get_equity()
            equity = _effective_equity(ctx, ib_equity)
            if not warned_cap and config.capital.max_deploy_usd > ib_equity:
                _mark_event(
                    ctx,
                    "WARN",
                    (
                        f"capital.max_deploy_usd ({config.capital.max_deploy_usd:.2f}) "
                        f"is above IB equity ({ib_equity:.2f}); using IB equity."
                    ),
                )
                warned_cap = True

            _ensure_day_start_equity(ctx, equity)
            positions = broker.get_positions()
            if data_feed is None:
                for symbol in config.symbols:
                    if ctx.shutdown:
                        _mark_event(ctx, "INFO", "shutdown requested, stopping symbol processing")
                        break
                    closes = broker.get_recent_closes(
                        symbol=symbol,
                        duration=config.strategy.duration,
                        bar_size=config.strategy.bar_size,
                    )
                    _execute_symbol(ctx, symbol, equity, positions, closes)
            else:
                symbol = data_feed.next_symbol(timeout_seconds=1.0)
                if not symbol:
                    continue
                update = data_feed.get_latest(symbol)
                if update is None:
                    continue
                _execute_symbol(ctx, symbol, equity, positions, update.closes)

        except Exception as exc:  # noqa: BLE001
            _mark_event(ctx, "ERROR", f"loop error: {exc}")
        finally:
            if not ctx.shutdown:
                _sleep_interruptible(ctx, 0.2 if data_feed is not None else config.strategy.loop_interval_seconds)

    if data_feed is not None:
        data_feed.stop()

    _mark_event(ctx, "INFO", f"engine stopped at {datetime.now(UTC).isoformat()}")
