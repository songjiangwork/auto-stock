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
- Strategy: configurable strategy composition (`ma` + optional `rsi`)
- Runtime: long-running process (`autostock run`)
- Risk:
  - Max 20% capital per symbol
  - 8% stop-loss per symbol
  - Symbol daily loss guard
  - Account daily drawdown guard
  - Max open positions guard
  - Consecutive loss circuit breaker

## Strategy Composition
- Strategies are config-driven under `strategy_combo`.
- Supported strategies now:
  - `ma` (moving-average crossover)
  - `rsi` (oversold/overbought)
- Supported combination modes:
  - `weighted` (recommended)
  - `vote`
  - `unanimous`
  - `priority`
- Example to combine MA and RSI:
```yaml
strategy_combo:
  enabled_strategies: [ma, rsi]
  combination_mode: weighted
  decision_threshold: 0.2
  weights:
    ma: 0.7
    rsi: 0.3
  rsi:
    window: 14
    oversold: 30
    overbought: 70
```

## Prerequisites
1. Install Python 3.10+.
2. Install and run IB Gateway or TWS.
3. Enable API access in TWS/Gateway.
4. Use paper account port (default `7497`).
5. `ib.account` behavior:
  - If `ib.account` is set to a real account id (e.g. `DU1234567`), that account is used and validated.
  - If `ib.account` is empty (or placeholder like `DUXXXXXXX`), the app auto-selects the first available IB account after connect.
  - If no account is available, startup fails with an error.

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

## Testing
```bash
.venv\Scripts\python -m pytest -q
```

## Notes
- The process trades only during regular US market hours (Mon-Fri, 09:30-16:00 America/New_York).
- `data/autostock.db` stores orders, snapshots, and events.
- On startup, the engine performs broker sync:
  - Pulls new IB executions since the last local execution timestamp.
  - Upserts executions into local ledger and rebuilds daily symbol realized PnL and consecutive-loss state.
  - Uses IB positions as the source of truth for current holdings.
- `backtest` always runs two scenarios in one command:
  - `60 D + 5 mins`
  - `2 Y + 1 day`
- Recommended production decisioning is based on the `1 day` scenario; `5 mins` is for research comparison.
- `backtest` auto-exports trades to:
  - `data/backtests/<SYMBOL>/<YYYYMMDD_HHMMSS>/5min.csv`
  - `data/backtests/<SYMBOL>/<YYYYMMDD_HHMMSS>/1d.csv`
  - `data/backtests/<SYMBOL>/<YYYYMMDD_HHMMSS>/summary.csv`
  - `data/backtests/_master_summary.csv` (cross-batch aggregate table)
- `backtest` includes execution realism controls from config:
  - `backtest.slippage_bps`
  - `backtest.commission_per_order`
  - `backtest.min_order_notional`
- Exported CSV includes trade-level P/L and running totals:
  - `profit_loss_abs`, `profit_loss_pct`
  - `cum_profit_loss_abs`, `cum_profit_loss_pct`
  - `cum_equity`
