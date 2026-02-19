from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys

from autostock.backtest import export_backtest_trades, run_backtest, summarize_backtest
from autostock.config import AppConfig, load_config, load_default_config
from autostock.database import Database
from autostock.engine import run_loop, us_market_is_open
from autostock.ib_client import IBClient
from autostock.reporting import render_daily_report, render_status
from autostock.risk import RiskManager


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autostock", description="Automated trading CLI (POC)")
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Optional path to YAML config. If omitted, loads config/config.yaml overlaid by config/config.local.yaml.",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check config, DB, and IB connectivity")
    sub.add_parser("run", help="Run strategy loop as a long-running process")
    flatten_parser = sub.add_parser("flatten", help="Close existing positions for current IB account")
    flatten_parser.add_argument(
        "--ticker",
        default="",
        help="Optional single ticker to close. If omitted, all open positions are closed.",
    )
    flatten_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview close orders without sending them.",
    )
    flatten_parser.add_argument(
        "--force",
        action="store_true",
        help="Use sidecar client_id (+1) for flatten; useful if run is active.",
    )
    sub.add_parser("status", help="Show latest local snapshots")
    sub.add_parser("report", help="Show last 24h local report")
    backtest_parser = sub.add_parser("backtest", help="Run MA crossover backtest using IB historical bars")
    backtest_parser.add_argument(
        "--initial-capital",
        type=float,
        default=None,
        help="Initial capital per symbol for simulation (default: uses capital.max_deploy_usd)",
    )
    backtest_parser.add_argument(
        "--ticker",
        default="",
        help="Optional single ticker to backtest (e.g. TSLA). If omitted, all configured symbols are used.",
    )
    return parser


def select_client_id(base_client_id: int, sidecar: bool) -> int:
    return base_client_id + 1 if sidecar else base_client_id


def flatten_uses_sidecar(force: bool) -> bool:
    return force


def _broker_for_command(config: AppConfig, sidecar_client: bool) -> IBClient:
    client_id = select_client_id(config.ib.client_id, sidecar_client)
    ib_cfg = replace(config.ib, client_id=client_id)
    return IBClient(ib_cfg)


def _load_effective_config(config_path: str | None) -> AppConfig:
    if config_path:
        return load_config(config_path)
    return load_default_config()


def _doctor(config_path: str) -> int:
    config = _load_effective_config(config_path)
    db = Database(config.database_path)
    db.log_event("INFO", "doctor command started")
    broker = _broker_for_command(config, sidecar_client=True)

    print("Config load: OK")
    print(f"Trading mode: {config.ib.trading_mode}")
    print(f"Symbols: {', '.join(config.symbols)}")
    print(f"Capital cap: {config.capital.max_deploy_usd:.2f} USD")
    print(f"Market open now ({config.timezone}): {us_market_is_open(config.timezone)}")
    print(f"Database: OK ({config.database_path})")

    try:
        broker.connect()
        print("IB connection: OK")
        print(f"Selected account: {broker.get_active_account()}")
        equity = broker.get_equity()
        print(f"Net liquidation: {equity:.2f}")
        broker.ensure_symbols(config.symbols)
        print("Contract qualification: OK")
    finally:
        broker.disconnect()
        db.close()
    return 0


def _run(config_path: str) -> int:
    config = _load_effective_config(config_path)
    db = Database(config.database_path)
    broker = _broker_for_command(config, sidecar_client=False)
    risk = RiskManager(config.risk)
    try:
        broker.connect()
        run_loop(config, db, broker, risk)
    finally:
        broker.disconnect()
        db.close()
    return 0


def _status(config_path: str) -> int:
    config = _load_effective_config(config_path)
    db = Database(config.database_path)
    try:
        print(render_status(db))
    finally:
        db.close()
    return 0


def _flatten(config_path: str, ticker: str, dry_run: bool, force: bool) -> int:
    config = _load_effective_config(config_path)
    broker = _broker_for_command(config, sidecar_client=flatten_uses_sidecar(force))
    try:
        broker.connect()
        account = broker.get_active_account()
        positions = broker.get_positions()

        target = ticker.strip().upper()
        to_close = [
            pos
            for symbol, pos in positions.items()
            if pos.quantity != 0 and (not target or symbol == target)
        ]
        if not to_close:
            print("No matching open positions to close.")
            return 0

        print(f"Selected account: {account}")
        print(f"Positions to close: {len(to_close)}")
        for pos in sorted(to_close, key=lambda x: x.symbol):
            side = "SELL" if pos.quantity > 0 else "BUY"
            qty = int(abs(pos.quantity))
            if dry_run:
                print(f"[DRY-RUN] {pos.symbol}: {side} {qty}")
                continue
            status = broker.close_position(pos.symbol, pos.quantity)
            print(f"{pos.symbol}: {side} {qty} -> {status}")
    finally:
        broker.disconnect()
    return 0


def _report(config_path: str) -> int:
    config = _load_effective_config(config_path)
    db = Database(config.database_path)
    try:
        print(render_daily_report(db))
    finally:
        db.close()
    return 0


def _print_backtest_block(title: str, results: list) -> None:
    print(title)
    for res in results:
        win_rate = (res.wins / res.trades * 100.0) if res.trades else 0.0
        print(
            f"- {res.symbol}: bars={res.bars}, trades={res.trades}, wins={res.wins}, losses={res.losses}, "
            f"win_rate={win_rate:.1f}%, pnl={res.pnl:.2f}, return={res.return_pct*100:.2f}%, "
            f"maxDD={res.max_drawdown_pct*100:.2f}%"
        )
    summary = summarize_backtest(results)
    print(
        f"Summary: symbols={summary.total_symbols}, total_trades={summary.total_trades}, "
        f"total_pnl={summary.total_pnl:.2f}, avg_return={summary.avg_return_pct*100:.2f}%, "
        f"avg_maxDD={summary.avg_max_drawdown_pct*100:.2f}%"
    )


def _export_backtest_artifacts(
    results_5m: list,
    results_1d: list,
    timestamp: str,
    initial_capital: float,
    config,
) -> None:
    by_symbol_5m = {r.symbol: r for r in results_5m}
    by_symbol_1d = {r.symbol: r for r in results_1d}
    symbols = sorted(set(by_symbol_5m) | set(by_symbol_1d))
    master_path = Path("data") / "backtests" / "_master_summary.csv"
    write_master_header = not master_path.exists()
    master_path.parent.mkdir(parents=True, exist_ok=True)
    with master_path.open("a", newline="", encoding="utf-8") as master_f:
        master_writer = csv.writer(master_f)
        if write_master_header:
            master_writer.writerow(
                [
                    "batch",
                    "symbol",
                    "scenario",
                    "bars",
                    "trades",
                    "wins",
                    "losses",
                    "win_rate_pct",
                    "pnl",
                    "return_pct",
                    "max_drawdown_pct",
                    "initial_capital",
                    "combination_mode",
                    "enabled_strategies",
                    "decision_threshold",
                    "slippage_bps",
                    "commission_per_order",
                ]
            )

        for symbol in symbols:
            symbol_dir = Path("data") / "backtests" / symbol / timestamp
            symbol_dir.mkdir(parents=True, exist_ok=True)

            res_5m = by_symbol_5m.get(symbol)
            res_1d = by_symbol_1d.get(symbol)
            if res_5m is not None:
                path_5m = export_backtest_trades(
                    [res_5m],
                    str(symbol_dir / "5min.csv"),
                    initial_capital=initial_capital,
                )
                print(f"Trades exported: {path_5m}")
            if res_1d is not None:
                path_1d = export_backtest_trades(
                    [res_1d],
                    str(symbol_dir / "1d.csv"),
                    initial_capital=initial_capital,
                )
                print(f"Trades exported: {path_1d}")

            summary_path = symbol_dir / "summary.csv"
            with summary_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "scenario",
                        "symbol",
                        "bars",
                        "trades",
                        "wins",
                        "losses",
                        "win_rate_pct",
                        "pnl",
                        "return_pct",
                        "max_drawdown_pct",
                        "initial_capital",
                    ]
                )
                for scenario_name, res in [("5min", res_5m), ("1d", res_1d)]:
                    if res is None:
                        continue
                    win_rate = (res.wins / res.trades * 100.0) if res.trades else 0.0
                    row = [
                        scenario_name,
                        res.symbol,
                        res.bars,
                        res.trades,
                        res.wins,
                        res.losses,
                        f"{win_rate:.4f}",
                        f"{res.pnl:.2f}",
                        f"{res.return_pct*100:.4f}",
                        f"{res.max_drawdown_pct*100:.4f}",
                        f"{initial_capital:.2f}",
                    ]
                    writer.writerow(row)
                    master_writer.writerow(
                        row
                        + [
                            config.strategy_combo.combination_mode,
                            ";".join(config.strategy_combo.enabled_strategies),
                            f"{config.strategy_combo.decision_threshold:.4f}",
                            f"{config.backtest.slippage_bps:.4f}",
                            f"{config.backtest.commission_per_order:.4f}",
                        ]
                    )
            print(f"Summary exported: {summary_path}")
    print(f"Master summary updated: {master_path}")


def _backtest(config_path: str, initial_capital: float | None, ticker: str) -> int:
    config = _load_effective_config(config_path)
    selected_symbols = [ticker.strip().upper()] if ticker.strip() else config.symbols
    effective_initial_capital = (
        float(initial_capital) if initial_capital is not None else float(config.capital.max_deploy_usd)
    )

    broker = _broker_for_command(config, sidecar_client=True)
    try:
        broker.connect()
        broker.ensure_symbols(selected_symbols)
        results_5m = run_backtest(
            config,
            broker,
            initial_capital=effective_initial_capital,
            duration="60 D",
            bar_size="5 mins",
            symbols=selected_symbols,
        )
        results_1d = run_backtest(
            config,
            broker,
            initial_capital=effective_initial_capital,
            duration="2 Y",
            bar_size="1 day",
            symbols=selected_symbols,
        )
    finally:
        broker.disconnect()

    print(f"Backtest initial capital per symbol: {effective_initial_capital:.2f}")
    _print_backtest_block("Backtest results (60 D + 5 mins):", results_5m)
    _print_backtest_block("Backtest results (2 Y + 1 day):", results_1d)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _export_backtest_artifacts(results_5m, results_1d, timestamp, effective_initial_capital, config)
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    cmd = args.command
    if cmd == "doctor":
        return _doctor(args.config)
    if cmd == "run":
        return _run(args.config)
    if cmd == "flatten":
        return _flatten(args.config, args.ticker, args.dry_run, args.force)
    if cmd == "status":
        return _status(args.config)
    if cmd == "report":
        return _report(args.config)
    if cmd == "backtest":
        return _backtest(args.config, args.initial_capital, args.ticker)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
