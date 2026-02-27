from __future__ import annotations

from pathlib import Path

from autostock.backtest_grid_report import write_leaderboard_html, write_trades_html


def test_write_leaderboard_html_from_grid_summary_csv() -> None:
    base_dir = Path("data") / "test_backtest_grid_report"
    base_dir.mkdir(parents=True, exist_ok=True)
    summary_path = base_dir / "grid_summary.csv"
    summary_path.write_text(
        "\n".join(
            [
                "run_id,scenario,duration,bar_size,mode,symbols,total_symbols,total_trades,total_pnl,avg_return_pct,avg_max_drawdown_pct,portfolio_return_pct,overrides",
                "1,5min,2 Y,5 mins,portfolio,MSFT,1,100,1200.00,1.20,12.30,2.40,strategy.short_window=20",
                "2,1d,2 Y,1 day,portfolio,MSFT,1,20,3400.00,3.40,8.20,6.80,strategy.short_window=30",
            ]
        ),
        encoding="utf-8",
    )
    output_path = base_dir / "leaderboard.html"
    out = write_leaderboard_html(summary_path, output_path)
    assert out == output_path
    html = output_path.read_text(encoding="utf-8")
    assert "Backtest Grid Leaderboard" in html
    assert "All Scenarios" in html
    assert ">Scenario<" in html
    assert "<h2>5min</h2>" in html
    assert "<h2>1d</h2>" in html
    assert "data/test_backtest_grid_report/grid_summary.csv" in html.replace("\\", "/")
    assert "strategy.short_window=20" in html
    assert "sortTable" in html


def test_write_trades_html_from_trades_csv() -> None:
    base_dir = Path("data") / "test_backtest_grid_report"
    base_dir.mkdir(parents=True, exist_ok=True)
    trades_path = base_dir / "run_001__1d__trades.csv"
    trades_path.write_text(
        "\n".join(
            [
                "symbol,entry_time,exit_time,entry_price,exit_price,shares,entry_value,exit_value,profit_loss_abs,profit_loss_pct,cum_profit_loss_abs,cum_profit_loss_pct,cum_equity,exit_reason",
                "MSFT,2024-01-01,2024-01-10,100,110,10,1000,1100,90,0.09,90,0.0018,50090,STRATEGY_SELL",
                "MSFT,2024-01-12,2024-01-20,120,108,8,960,864,-98,-0.10,-8,-0.0001,49992,STOP_LOSS",
            ]
        ),
        encoding="utf-8",
    )
    output_path = base_dir / "run_001__1d__trades.html"
    out = write_trades_html(trades_path, output_path)
    assert out == output_path
    html = output_path.read_text(encoding="utf-8")
    assert "Backtest Trades" in html
    assert "Rows: 2" in html
    assert "STOP_LOSS" in html
    assert "sortTable" in html
