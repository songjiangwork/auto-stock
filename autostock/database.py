from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                signal TEXT NOT NULL,
                status TEXT NOT NULL,
                price REAL,
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                position REAL NOT NULL,
                avg_cost REAL NOT NULL,
                last_price REAL NOT NULL,
                unrealized_pnl REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS executions (
                exec_id TEXT PRIMARY KEY,
                ts_utc TEXT NOT NULL,
                account TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                order_id INTEGER,
                perm_id INTEGER
            );
            """
        )
        self.conn.commit()

    def log_event(self, level: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO events (ts_utc, level, message) VALUES (?, ?, ?)",
            (utc_now_iso(), level.upper(), message),
        )
        self.conn.commit()

    def record_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        signal: str,
        status: str,
        price: float | None = None,
        note: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO orders (ts_utc, symbol, side, quantity, signal, status, price, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (utc_now_iso(), symbol, side, quantity, signal, status, price, note),
        )
        self.conn.commit()

    def record_snapshot(
        self, symbol: str, position: float, avg_cost: float, last_price: float, unrealized_pnl: float
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO snapshots (ts_utc, symbol, position, avg_cost, last_price, unrealized_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (utc_now_iso(), symbol, position, avg_cost, last_price, unrealized_pnl),
        )
        self.conn.commit()

    def set_state(self, key: str, value: Any) -> None:
        encoded = json.dumps(value)
        self.conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, encoded),
        )
        self.conn.commit()

    def delete_state_prefix(self, prefix: str) -> None:
        self.conn.execute("DELETE FROM app_state WHERE key LIKE ?", (f"{prefix}%",))
        self.conn.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def upsert_execution(
        self,
        exec_id: str,
        ts_utc: str,
        account: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_id: int | None,
        perm_id: int | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO executions (exec_id, ts_utc, account, symbol, side, quantity, price, order_id, perm_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exec_id) DO UPDATE SET
                ts_utc=excluded.ts_utc,
                account=excluded.account,
                symbol=excluded.symbol,
                side=excluded.side,
                quantity=excluded.quantity,
                price=excluded.price,
                order_id=excluded.order_id,
                perm_id=excluded.perm_id
            """,
            (exec_id, ts_utc, account, symbol, side, quantity, price, order_id, perm_id),
        )
        self.conn.commit()

    def latest_execution_ts(self) -> str | None:
        row = self.conn.execute("SELECT MAX(ts_utc) AS ts FROM executions").fetchone()
        if not row or row["ts"] is None:
            return None
        return str(row["ts"])

    def executions_ordered(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM executions ORDER BY ts_utc ASC, exec_id ASC"
        ).fetchall()

    def rebuild_daily_risk_state(self, tz_name: str) -> tuple[dict[str, float], int]:
        rows = self.executions_ordered()
        if not rows:
            return {}, 0

        today = datetime.now(ZoneInfo(tz_name)).date().isoformat()
        position_qty: dict[str, float] = defaultdict(float)
        avg_cost: dict[str, float] = defaultdict(float)
        symbol_realized_today: dict[str, float] = defaultdict(float)
        consecutive_losses_today = 0

        for row in rows:
            symbol = str(row["symbol"])
            side = str(row["side"]).upper()
            qty = float(row["quantity"])
            price = float(row["price"])
            ts = datetime.fromisoformat(str(row["ts_utc"]))
            trade_day = ts.astimezone(ZoneInfo(tz_name)).date().isoformat()

            current_qty = position_qty[symbol]
            current_avg = avg_cost[symbol]

            if side in {"BUY", "BOT"}:
                new_qty = current_qty + qty
                if new_qty <= 0:
                    position_qty[symbol] = 0.0
                    avg_cost[symbol] = 0.0
                else:
                    avg_cost[symbol] = ((current_qty * current_avg) + (qty * price)) / new_qty
                    position_qty[symbol] = new_qty
                continue

            if side in {"SELL", "SLD"}:
                sell_qty = min(current_qty, qty) if current_qty > 0 else qty
                realized = (price - current_avg) * sell_qty
                position_qty[symbol] = max(0.0, current_qty - qty)
                if position_qty[symbol] == 0:
                    avg_cost[symbol] = 0.0
                if trade_day == today:
                    symbol_realized_today[symbol] += realized
                    if realized < 0:
                        consecutive_losses_today += 1
                    else:
                        consecutive_losses_today = 0
                continue

        return dict(symbol_realized_today), consecutive_losses_today

    def latest_snapshots(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT s.*
            FROM snapshots s
            INNER JOIN (
                SELECT symbol, MAX(ts_utc) AS max_ts
                FROM snapshots
                GROUP BY symbol
            ) x
              ON x.symbol = s.symbol AND x.max_ts = s.ts_utc
            ORDER BY s.symbol
            """
        ).fetchall()

    def orders_since(self, iso_ts: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM orders WHERE ts_utc >= ? ORDER BY ts_utc DESC",
            (iso_ts,),
        ).fetchall()

    def events_since(self, iso_ts: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events WHERE ts_utc >= ? ORDER BY ts_utc DESC",
            (iso_ts,),
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
