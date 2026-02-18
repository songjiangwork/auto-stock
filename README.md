# AutoStock (POC V1)

CLI-first proof-of-concept for automated US stock/ETF trading with:
- Python
- IBKR Paper Trading via `ib_insync`
- SQLite state/log storage
- YAML config
- Moving-average crossover strategy

## Scope (V1)
- Instruments: US stocks/ETFs (options reserved for later)
- Mode: IB paper trading only
- Strategy: 20/50 MA crossover
  - Live default timeframe: `2 Y` history with `1 day` bars
- Runtime: long-running process (`autostock run`)
- Risk:
  - Max 20% capital per symbol
  - 8% stop-loss per symbol
  - ATR-based volatility position sizing (with 20% cap)
  - Symbol daily loss guard
  - Account daily drawdown guard
  - Trend filter: allow new long entries only when `SPY > MA200`

## Prerequisites
1. Install Python 3.10+.
2. Install and run IB Gateway or TWS.
3. Enable API access in TWS/Gateway.
4. Use paper account port (default `7497`).
5. Update `config/config.yaml` with your paper account id (`DU...`).

## Install
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

## Commands
```bash
autostock -c config/config.yaml doctor
autostock -c config/config.yaml run
autostock -c config/config.yaml status
autostock -c config/config.yaml backtest
autostock -c config/config.yaml backtest --initial-capital 120000
autostock -c config/config.yaml backtest --ticker TSLA
autostock -c config/config.yaml report
```

## Notes
- The process trades only during regular US market hours (Mon-Fri, 09:30-16:00 America/New_York).
- `data/autostock.db` stores orders, snapshots, and events.
- `backtest` always runs two scenarios in one command:
  - `60 D + 5 mins`
  - `2 Y + 1 day`
- Recommended production decisioning is based on the `1 day` scenario; `5 mins` is for research comparison.
- `backtest` auto-exports trades to:
  - `data/backtests/<SYMBOL>/<YYYYMMDD_HHMMSS>/5min.csv`
  - `data/backtests/<SYMBOL>/<YYYYMMDD_HHMMSS>/1d.csv`
  - `data/backtests/<SYMBOL>/<YYYYMMDD_HHMMSS>/summary.csv`
- Exported CSV includes trade-level P/L and running totals:
  - `profit_loss_abs`, `profit_loss_pct`
  - `cum_profit_loss_abs`, `cum_profit_loss_pct`
  - `cum_equity`
