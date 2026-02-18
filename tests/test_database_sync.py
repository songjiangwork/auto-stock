from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autostock.database import Database


def test_rebuild_daily_risk_state_tracks_symbol_pnl_and_loss_streak() -> None:
    db = Database(":memory:")
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        yesterday = today - timedelta(days=1)
        # Day 1 baseline position build-up.
        db.upsert_execution(
            exec_id="1",
            ts_utc=f"{yesterday.isoformat()}T14:00:00+00:00",
            account="DU1",
            symbol="AAA",
            side="BUY",
            quantity=10,
            price=100.0,
            order_id=1,
            perm_id=101,
        )
        # Day 2: one losing sell, then one winning sell.
        db.upsert_execution(
            exec_id="2",
            ts_utc=f"{today.isoformat()}T14:00:00+00:00",
            account="DU1",
            symbol="AAA",
            side="SELL",
            quantity=5,
            price=90.0,
            order_id=2,
            perm_id=102,
        )
        db.upsert_execution(
            exec_id="3",
            ts_utc=f"{today.isoformat()}T15:00:00+00:00",
            account="DU1",
            symbol="AAA",
            side="SELL",
            quantity=5,
            price=110.0,
            order_id=3,
            perm_id=103,
        )

        pnl_by_symbol, consecutive_losses = db.rebuild_daily_risk_state("UTC")
        assert "AAA" in pnl_by_symbol
        # -50 + 50
        assert round(pnl_by_symbol["AAA"], 2) == 0.0
        # Winning sell resets loss streak.
        assert consecutive_losses == 0
    finally:
        db.close()
