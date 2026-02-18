from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from autostock.config import AppConfig
from autostock.ib_client import IBClient
from autostock.strategy import Signal, evaluate_combined_signal


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
    bars = broker.get_historical_bars(
        symbol=symbol,
        duration=use_duration,
        bar_size=use_bar_size,
    )
    closes = [bar.close for bar in bars]
    if len(closes) < 5:
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
            budget = cash * config.risk.max_position_pct
            order_shares = int(budget // price)
            if order_shares > 0:
                shares = order_shares
                cash -= shares * price
                entry = price
                entry_time = time_label
                in_position = True
        elif in_position and (signal_ == Signal.SELL or stop_loss):
            exit_reason = "STOP_LOSS" if stop_loss else "STRATEGY_SELL"
            cash += shares * price
            trade_pnl = (price - entry) * shares
            realized_pnl += trade_pnl
            return_pct = (price - entry) / entry if entry > 0 else 0.0
            trades_detail.append(
                BacktestTrade(
                    symbol=symbol,
                    entry_time=entry_time,
                    exit_time=time_label,
                    entry_price=entry,
                    exit_price=price,
                    shares=shares,
                    pnl=trade_pnl,
                    return_pct=return_pct,
                    exit_reason=exit_reason,
                )
            )
            if trade_pnl >= 0:
                wins += 1
            else:
                losses += 1
            shares = 0
            in_position = False
            entry = 0.0

        current_equity = cash + (shares * price if in_position else 0.0)
        equity_curve.append(current_equity)

    if in_position:
        final_price = aligned_prices[-1]
        final_time = aligned_bars[-1].date
        cash += shares * final_price
        trade_pnl = (final_price - entry) * shares
        realized_pnl += trade_pnl
        return_pct = (final_price - entry) / entry if entry > 0 else 0.0
        trades_detail.append(
            BacktestTrade(
                symbol=symbol,
                entry_time=entry_time,
                exit_time=final_time,
                entry_price=entry,
                exit_price=final_price,
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

    trades = len(trades_detail)
    return_pct = ((cash - initial_capital) / initial_capital) if initial_capital > 0 else 0.0

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
    return [
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
