from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys

from autostock.backtest import export_backtest_trades, run_backtest, summarize_backtest
from autostock.backtest_grid import (
    apply_overrides,
    generate_grid_overrides,
    grid_scenarios,
    load_grid_spec,
    normalize_parameter_grid,
)
from autostock.backtest_grid_report import write_leaderboard_html, write_trades_html
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
    backtest_parser.add_argument(
        "--mode",
        choices=["portfolio", "per-symbol"],
        default=None,
        help="Backtest capital mode (default: uses backtest.mode from config, which defaults to portfolio).",
    )
    backtest_parser.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=24.0,
        help="Reuse backtest historical cache when file age is within this TTL (default: 24).",
    )
    backtest_parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore backtest historical cache and force fresh IB fetch.",
    )
    backtest_grid_parser = sub.add_parser("backtest-grid", help="Run batch backtests using parameter grid YAML")
    backtest_grid_parser.add_argument(
        "--grid",
        default="config/backtest_grid.yaml",
        help="Path to grid YAML config (default: config/backtest_grid.yaml).",
    )
    backtest_grid_parser.add_argument(
        "--initial-capital",
        type=float,
        default=None,
        help="Initial capital (default: uses capital.max_deploy_usd).",
    )
    backtest_grid_parser.add_argument(
        "--ticker",
        default="",
        help="Optional single ticker to backtest (e.g. TSLA). If omitted, all configured symbols are used.",
    )
    backtest_grid_parser.add_argument(
        "--mode",
        choices=["portfolio", "per-symbol"],
        default=None,
        help="Backtest capital mode (default: uses backtest.mode from config).",
    )
    backtest_grid_parser.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=24.0,
        help="Reuse backtest historical cache when file age is within this TTL (default: 24).",
    )
    backtest_grid_parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore backtest historical cache and force fresh IB fetch.",
    )
    backtest_grid_report_parser = sub.add_parser(
        "backtest-grid-report", help="Generate sortable HTML leaderboard from a grid_summary.csv"
    )
    backtest_grid_report_parser.add_argument(
        "--summary",
        required=True,
        help="Path to grid summary CSV (for example data/backtests/grid/<timestamp>/grid_summary.csv).",
    )
    backtest_grid_report_parser.add_argument(
        "--output",
        default="",
        help="Optional output HTML path (default: same folder as summary, name leaderboard.html).",
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


def _print_backtest_block(title: str, results: list, mode: str, initial_capital: float) -> None:
    print(title)
    for res in results:
        win_rate = (res.wins / res.trades * 100.0) if res.trades else 0.0
        return_label = "return_contribution" if mode == "portfolio" else "return"
        print(
            f"- {res.symbol}: bars={res.bars}, trades={res.trades}, wins={res.wins}, losses={res.losses}, "
            f"win_rate={win_rate:.1f}%, pnl={res.pnl:.2f}, {return_label}={res.return_pct*100:.2f}%, "
            f"maxDD={res.max_drawdown_pct*100:.2f}%"
        )
    summary = summarize_backtest(results)
    if mode == "portfolio":
        portfolio_return_pct = (summary.total_pnl / initial_capital * 100.0) if initial_capital > 0 else 0.0
        print(
            f"Summary: symbols={summary.total_symbols}, total_trades={summary.total_trades}, "
            f"total_pnl={summary.total_pnl:.2f}, portfolio_return={portfolio_return_pct:.2f}%, "
            f"avg_symbol_maxDD={summary.avg_max_drawdown_pct*100:.2f}%"
        )
    else:
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
    mode: str,
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
                    "backtest_mode",
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
                        mode,
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


def _backtest(
    config_path: str,
    initial_capital: float | None,
    ticker: str,
    mode_override: str | None,
    cache_ttl_hours: float,
    refresh_cache: bool,
) -> int:
    config = _load_effective_config(config_path)
    selected_symbols = [ticker.strip().upper()] if ticker.strip() else config.symbols
    effective_initial_capital = (
        float(initial_capital) if initial_capital is not None else float(config.capital.max_deploy_usd)
    )
    mode = str(mode_override or getattr(config.backtest, "mode", "portfolio")).lower()

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
            mode=mode,
            cache_ttl_hours=cache_ttl_hours,
            refresh_cache=refresh_cache,
        )
        results_1d = run_backtest(
            config,
            broker,
            initial_capital=effective_initial_capital,
            duration="2 Y",
            bar_size="1 day",
            symbols=selected_symbols,
            mode=mode,
            cache_ttl_hours=cache_ttl_hours,
            refresh_cache=refresh_cache,
        )
    finally:
        broker.disconnect()

    if mode == "portfolio":
        print(f"Backtest initial portfolio capital: {effective_initial_capital:.2f}")
    else:
        print(f"Backtest initial capital per symbol: {effective_initial_capital:.2f}")
    print(f"Backtest mode: {mode}")
    _print_backtest_block("Backtest results (60 D + 5 mins):", results_5m, mode, effective_initial_capital)
    _print_backtest_block("Backtest results (2 Y + 1 day):", results_1d, mode, effective_initial_capital)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _export_backtest_artifacts(results_5m, results_1d, timestamp, effective_initial_capital, mode, config)
    return 0


def _format_override(overrides: dict[str, object]) -> str:
    return ";".join(f"{k}={overrides[k]}" for k in sorted(overrides.keys()))


def _safe_filename_token(text: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(text).strip())
    out = out.strip("_")
    while "__" in out:
        out = out.replace("__", "_")
    return out or "default"


def _backtest_grid(
    config_path: str,
    grid_path: str,
    initial_capital: float | None,
    ticker: str,
    mode_override: str | None,
    cache_ttl_hours: float,
    refresh_cache: bool,
) -> int:
    base_config = _load_effective_config(config_path)
    raw_grid = load_grid_spec(grid_path)
    param_grid = normalize_parameter_grid(raw_grid)
    scenarios = grid_scenarios(raw_grid)
    overrides_list = generate_grid_overrides(param_grid)
    mode = str(mode_override or getattr(base_config.backtest, "mode", "portfolio")).lower()
    selected_symbols = [ticker.strip().upper()] if ticker.strip() else base_config.symbols
    effective_initial_capital = (
        float(initial_capital) if initial_capital is not None else float(base_config.capital.max_deploy_usd)
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("data") / "backtests" / "grid" / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "grid_summary.csv"
    trades_dir = out_dir / "trades"
    trades_dir.mkdir(parents=True, exist_ok=True)
    trades_index_path = trades_dir / "_index.csv"
    total_runs = len(overrides_list) * len(scenarios)

    print(f"Grid file: {grid_path}")
    print(f"Symbols: {', '.join(selected_symbols)}")
    print(f"Mode: {mode}")
    print(f"Initial capital: {effective_initial_capital:.2f}")
    print(f"Cache TTL hours: {cache_ttl_hours:.2f} (refresh={refresh_cache})")
    print(f"Scenarios: {len(scenarios)}, parameter sets: {len(overrides_list)}, total runs: {total_runs}")

    with summary_path.open("w", newline="", encoding="utf-8") as f, trades_index_path.open(
        "w", newline="", encoding="utf-8"
    ) as index_f:
        writer = csv.writer(f)
        index_writer = csv.writer(index_f)
        writer.writerow(
            [
                "run_id",
                "scenario",
                "duration",
                "bar_size",
                "mode",
                "symbols",
                "total_symbols",
                "total_trades",
                "total_pnl",
                "avg_return_pct",
                "avg_max_drawdown_pct",
                "portfolio_return_pct",
                "overrides",
            ]
        )
        index_writer.writerow(["run_id", "scenario", "duration", "bar_size", "trades_file", "trades_html", "overrides"])

        broker = _broker_for_command(base_config, sidecar_client=True)
        try:
            broker.connect()
            broker.ensure_symbols(selected_symbols)
            run_id = 0
            for overrides in overrides_list:
                run_cfg = apply_overrides(base_config, overrides)
                for scenario in scenarios:
                    run_id += 1
                    results = run_backtest(
                        run_cfg,
                        broker,
                        initial_capital=effective_initial_capital,
                        duration=scenario["duration"],
                        bar_size=scenario["bar_size"],
                        symbols=selected_symbols,
                        mode=mode,
                        cache_ttl_hours=cache_ttl_hours,
                        refresh_cache=refresh_cache,
                    )
                    scenario_name = str(scenario["name"])
                    trades_file = (
                        trades_dir / f"run_{run_id:03d}__{_safe_filename_token(scenario_name)}__trades.csv"
                    )
                    export_backtest_trades(
                        results,
                        str(trades_file),
                        initial_capital=effective_initial_capital,
                    )
                    trades_html = write_trades_html(trades_file)
                    summary = summarize_backtest(results)
                    portfolio_return_pct = (
                        (summary.total_pnl / effective_initial_capital * 100.0)
                        if effective_initial_capital > 0
                        else 0.0
                    )
                    writer.writerow(
                        [
                            run_id,
                            scenario["name"],
                            scenario["duration"],
                            scenario["bar_size"],
                            mode,
                            ";".join(selected_symbols),
                            summary.total_symbols,
                            summary.total_trades,
                            f"{summary.total_pnl:.2f}",
                            f"{summary.avg_return_pct*100:.4f}",
                            f"{summary.avg_max_drawdown_pct*100:.4f}",
                            f"{portfolio_return_pct:.4f}",
                            _format_override(overrides),
                        ]
                    )
                    index_writer.writerow(
                        [
                            run_id,
                            scenario_name,
                            scenario["duration"],
                            scenario["bar_size"],
                            str(trades_file),
                            str(trades_html),
                            _format_override(overrides),
                        ]
                    )
                    print(
                        f"[{run_id}/{total_runs}] {scenario['name']}: "
                        f"pnl={summary.total_pnl:.2f}, trades={summary.total_trades}, overrides={_format_override(overrides)}"
                    )
        finally:
            broker.disconnect()

    print(f"Grid summary exported: {summary_path}")
    print(f"Grid trades exported: {trades_dir}")
    print(f"Grid trades index exported: {trades_index_path}")
    leaderboard_path = write_leaderboard_html(summary_path)
    print(f"Leaderboard exported: {leaderboard_path}")
    return 0


def _backtest_grid_report(summary_path: str, output_path: str) -> int:
    out = write_leaderboard_html(summary_path, output_path or None)
    print(f"Leaderboard exported: {out}")
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
        return _backtest(
            args.config,
            args.initial_capital,
            args.ticker,
            args.mode,
            args.cache_ttl_hours,
            args.refresh_cache,
        )
    if cmd == "backtest-grid":
        return _backtest_grid(
            args.config,
            args.grid,
            args.initial_capital,
            args.ticker,
            args.mode,
            args.cache_ttl_hours,
            args.refresh_cache,
        )
    if cmd == "backtest-grid-report":
        return _backtest_grid_report(args.summary, args.output)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
