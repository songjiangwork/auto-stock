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
- Capital control:
  - `capital.max_deploy_usd` caps strategy deployable capital (default `10000` USD), independent of full IB paper balance.
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

## Config Split
- `config/config.yaml` is a shareable template.
- Put personal symbols/strategy/risk/capital values in `config/config.local.yaml` (gitignored).
- If you run without `-c`, the app loads layered config by default:
  - base: `config/config.yaml`
  - override: `config/config.local.yaml` (if present)
- Run with local config:
```bash
autostock -c config/config.local.yaml doctor
autostock -c config/config.local.yaml run
autostock -c config/config.local.yaml backtest
```

## Commands
```bash
autostock doctor
autostock run
autostock flatten --dry-run
autostock flatten --ticker QCOM
autostock status
autostock backtest
autostock backtest --initial-capital 120000
autostock backtest --ticker TSLA
autostock report
```

Client ID behavior:
- `run` uses configured `ib.client_id` from YAML.
- `doctor` and `backtest` automatically use `ib.client_id + 1` so they can run in another terminal while `run` is active.
- `flatten` uses configured `ib.client_id` by default; pass `--force` to use `ib.client_id + 1`.

Capital behavior:
- `run` uses `effective_equity = min(IB NetLiquidation, capital.max_deploy_usd)`.
- `backtest` uses `capital.max_deploy_usd` by default, unless `--initial-capital` is provided.

## Testing
```bash
.venv\Scripts\python -m pytest -q
```

## Notes
- The process trades only during regular US market hours (Mon-Fri, 09:30-16:00 America/New_York).
- `data/autostock.db` stores orders, snapshots, and events.
- `flatten` closes positions on the selected IB account:
  - no ticker: close all open positions
  - `--ticker`: close one symbol only
  - `--dry-run`: preview orders without submitting
- Market orders are submitted with explicit `TIF=DAY` and `outsideRth=False` by default.
- On startup, the engine performs broker sync:
  - Pulls new IB executions since the last local execution timestamp.
  - Upserts executions into local ledger and rebuilds daily symbol realized PnL and consecutive-loss state.
  - Uses IB positions as the source of truth for current holdings.
- Shutdown behavior:
  - Press `Ctrl+C` to request graceful shutdown.
  - The engine finishes the current in-flight symbol operation, then stops processing new symbols and exits without waiting a full loop interval.
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
