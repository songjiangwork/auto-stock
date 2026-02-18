from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

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
