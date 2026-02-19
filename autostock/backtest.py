from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from autostock.config import AppConfig
from autostock.ib_client import IBClient
from autostock.strategy import Signal, evaluate_combined_signal


def _log(message: str, level: str = "INFO") -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{level}] [{ts}] {message}")


@dataclass(slots=True)
class BacktestTrade:
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    return_pct: float
    exit_reason: str


@dataclass(slots=True)
class BacktestResult:
    symbol: str
    bars: int
    trades: int
    wins: int
    losses: int
    pnl: float
    return_pct: float
    max_drawdown_pct: float
    trades_detail: list[BacktestTrade]


@dataclass(slots=True)
class BacktestSummary:
    total_symbols: int
    total_trades: int
    total_pnl: float
    avg_return_pct: float
    avg_max_drawdown_pct: float


def _max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _slippage_multiplier(side: str, slippage_bps: float) -> float:
    shift = slippage_bps / 10000.0
    if side.upper() == "BUY":
        return 1.0 + shift
    return 1.0 - shift


def run_backtest_for_symbol(
    config: AppConfig,
    broker: IBClient,
    symbol: str,
    initial_capital: float,
    duration: str | None = None,
    bar_size: str | None = None,
) -> BacktestResult:
    use_duration = duration or config.strategy.duration
    use_bar_size = bar_size or config.strategy.bar_size
    _log(f"{symbol}: fetching bars (duration={use_duration}, bar_size={use_bar_size})")
    bars = broker.get_historical_bars(
        symbol=symbol,
        duration=use_duration,
        bar_size=use_bar_size,
    )
    closes = [bar.close for bar in bars]
    if bars:
        _log(f"{symbol}: bars_loaded={len(bars)}, first={bars[0].date}, last={bars[-1].date}")
    else:
        _log(f"{symbol}: bars_loaded=0")
    if len(closes) < 5:
        _log(f"{symbol}: skipped (insufficient bars={len(closes)})")
        return BacktestResult(
            symbol=symbol,
            bars=len(closes),
            trades=0,
            wins=0,
            losses=0,
            pnl=0.0,
            return_pct=0.0,
            max_drawdown_pct=0.0,
            trades_detail=[],
        )

    aligned_prices = closes
    aligned_bars = bars

    in_position = False
    entry = 0.0
    entry_time = ""
    shares = 0
    cash = initial_capital
    realized_pnl = 0.0
    trades_detail: list[BacktestTrade] = []
    wins = 0
    losses = 0
    equity_curve = [initial_capital]
    consecutive_losses = 0
    blocked_by_consecutive = 0
    blocked_by_min_notional = 0

    for i in range(1, len(aligned_prices)):
        price = aligned_prices[i]
        time_label = aligned_bars[i].date
        signal_, _detail = evaluate_combined_signal(
            aligned_prices[: i + 1],
            config.strategy,
            config.strategy_combo,
        )
        stop_loss = in_position and price <= entry * (1 - config.risk.stop_loss_pct)

        if signal_ == Signal.BUY and not in_position:
            if consecutive_losses >= config.risk.max_consecutive_losses:
                blocked_by_consecutive += 1
                continue
            budget = cash * config.risk.max_position_pct
            buy_fill = price * _slippage_multiplier("BUY", config.backtest.slippage_bps)
            order_shares = int(budget // buy_fill)
            if order_shares > 0:
                notional = order_shares * buy_fill
                if notional < config.backtest.min_order_notional:
                    blocked_by_min_notional += 1
                    continue
                shares = order_shares
                cash -= notional
                cash -= config.backtest.commission_per_order
                entry = buy_fill
                entry_time = time_label
                in_position = True
                _log(
                    f"{symbol}: BUY {shares} @ {entry:.2f} on {entry_time} "
                    f"(cash={cash:.2f}, budget={budget:.2f})"
                )
        elif in_position and (signal_ == Signal.SELL or stop_loss):
            exit_reason = "STOP_LOSS" if stop_loss else "STRATEGY_SELL"
            sell_fill = price * _slippage_multiplier("SELL", config.backtest.slippage_bps)
            cash += shares * sell_fill
            cash -= config.backtest.commission_per_order
            trade_pnl = (sell_fill - entry) * shares - (2.0 * config.backtest.commission_per_order)
            realized_pnl += trade_pnl
            return_pct = (sell_fill - entry) / entry if entry > 0 else 0.0
            trades_detail.append(
                BacktestTrade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=time_label,
                    entry_price=entry,
                    exit_price=sell_fill,
                    shares=shares,
                    pnl=trade_pnl,
                    return_pct=return_pct,
                    exit_reason=exit_reason,
                )
            )
            if trade_pnl >= 0:
                wins += 1
                consecutive_losses = 0
            else:
                losses += 1
                consecutive_losses += 1
            _log(
                f"{symbol}: {exit_reason} {shares} @ {sell_fill:.2f} on {time_label} "
                f"(trade_pnl={trade_pnl:.2f}, cash={cash:.2f}, consecutive_losses={consecutive_losses})"
            )
            shares = 0
            in_position = False
            entry = 0.0

        current_equity = cash + (shares * price if in_position else 0.0)
        equity_curve.append(current_equity)

    if in_position:
        final_price = aligned_prices[-1]
        final_time = aligned_bars[-1].date
        sell_fill = final_price * _slippage_multiplier("SELL", config.backtest.slippage_bps)
        cash += shares * sell_fill
        cash -= config.backtest.commission_per_order
        trade_pnl = (sell_fill - entry) * shares - (2.0 * config.backtest.commission_per_order)
        realized_pnl += trade_pnl
        return_pct = (sell_fill - entry) / entry if entry > 0 else 0.0
        trades_detail.append(
            BacktestTrade(
                symbol=symbol,
                entry_time=entry_time,
                exit_time=final_time,
                entry_price=entry,
                exit_price=sell_fill,
                shares=shares,
                pnl=trade_pnl,
                return_pct=return_pct,
                exit_reason="FORCED_EXIT_END",
            )
        )
        if trade_pnl >= 0:
            wins += 1
        else:
            losses += 1
        equity_curve.append(cash)
        _log(
            f"{symbol}: FORCED_EXIT_END {shares} @ {sell_fill:.2f} on {final_time} "
            f"(trade_pnl={trade_pnl:.2f}, cash={cash:.2f})"
        )

    trades = len(trades_detail)
    return_pct = ((cash - initial_capital) / initial_capital) if initial_capital > 0 else 0.0
    _log(
        f"{symbol}: completed bars={len(closes)}, trades={trades}, wins={wins}, losses={losses}, "
        f"pnl={realized_pnl:.2f}, return={return_pct*100:.2f}%, maxDD={_max_drawdown(equity_curve)*100:.2f}%, "
        f"blocked_consecutive={blocked_by_consecutive}, blocked_min_notional={blocked_by_min_notional}"
    )

    return BacktestResult(
        symbol=symbol,
        bars=len(closes),
        trades=trades,
        wins=wins,
        losses=losses,
        pnl=realized_pnl,
        return_pct=return_pct,
        max_drawdown_pct=_max_drawdown(equity_curve),
        trades_detail=trades_detail,
    )


def run_backtest(
    config: AppConfig,
    broker: IBClient,
    initial_capital: float = 100_000.0,
    duration: str | None = None,
    bar_size: str | None = None,
    symbols: list[str] | None = None,
) -> list[BacktestResult]:
    symbol_list = symbols if symbols is not None else config.symbols
    use_duration = duration or config.strategy.duration
    use_bar_size = bar_size or config.strategy.bar_size
    _log(
        f"batch start: symbols={len(symbol_list)}, duration={use_duration}, "
        f"bar_size={use_bar_size}, initial_capital={initial_capital:.2f}"
    )
    results = [
        run_backtest_for_symbol(
            config,
            broker,
            symbol,
            initial_capital,
            duration=duration,
            bar_size=bar_size,
        )
        for symbol in symbol_list
    ]
    summary = summarize_backtest(results)
    _log(
        f"batch end: symbols={summary.total_symbols}, trades={summary.total_trades}, "
        f"total_pnl={summary.total_pnl:.2f}, avg_return={summary.avg_return_pct*100:.2f}%, "
        f"avg_maxDD={summary.avg_max_drawdown_pct*100:.2f}%"
    )
    return results


def summarize_backtest(results: list[BacktestResult]) -> BacktestSummary:
    if not results:
        return BacktestSummary(0, 0, 0.0, 0.0, 0.0)
    total_trades = sum(r.trades for r in results)
    total_pnl = sum(r.pnl for r in results)
    avg_return = sum(r.return_pct for r in results) / len(results)
    avg_dd = sum(r.max_drawdown_pct for r in results) / len(results)
    return BacktestSummary(
        total_symbols=len(results),
        total_trades=total_trades,
        total_pnl=total_pnl,
        avg_return_pct=avg_return,
        avg_max_drawdown_pct=avg_dd,
    )


def export_backtest_trades(
    results: list[BacktestResult],
    output_path: str,
    initial_capital: float = 100_000.0,
) -> str:
    rows: list[BacktestTrade] = []
    for res in results:
        rows.extend(res.trades_detail)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "symbol",
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "shares",
                "entry_value",
                "exit_value",
                "profit_loss_abs",
                "profit_loss_pct",
                "cum_profit_loss_abs",
                "cum_profit_loss_pct",
                "cum_equity",
                "exit_reason",
            ]
        )
        cum_pnl = 0.0
        for row in rows:
            entry_value = row.entry_price * row.shares
            exit_value = row.exit_price * row.shares
            trade_pnl_abs = row.pnl
            trade_pnl_pct = row.return_pct
            cum_pnl += trade_pnl_abs
            cum_pnl_pct = (cum_pnl / initial_capital) if initial_capital > 0 else 0.0
            cum_equity = initial_capital + cum_pnl
            writer.writerow(
                [
                    row.symbol,
                    row.entry_time,
                    row.exit_time,
                    f"{row.entry_price:.6f}",
                    f"{row.exit_price:.6f}",
                    row.shares,
                    f"{entry_value:.2f}",
                    f"{exit_value:.2f}",
                    f"{trade_pnl_abs:.2f}",
                    f"{trade_pnl_pct:.6f}",
                    f"{cum_pnl:.2f}",
                    f"{cum_pnl_pct:.6f}",
                    f"{cum_equity:.2f}",
                    row.exit_reason,
                ]
            )
    return str(path)
