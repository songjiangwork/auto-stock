from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autostock.database import Database


def render_status(db: Database) -> str:
    snapshots = db.latest_snapshots()
    if not snapshots:
        return "No snapshots yet. Run `autostock run` first."

    lines = ["Latest snapshots:"]
    for row in snapshots:
        lines.append(
            f"- {row['symbol']}: pos={row['position']:.2f}, avg_cost={row['avg_cost']:.2f}, "
            f"last={row['last_price']:.2f}, unrealized={row['unrealized_pnl']:.2f}"
        )
    return "\n".join(lines)


def render_daily_report(db: Database) -> str:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    orders = db.orders_since(since)
    events = db.events_since(since)

    lines = ["Last 24h report:"]
    lines.append(f"Orders: {len(orders)}")
    buy = sum(1 for o in orders if o["side"] == "BUY")
    sell = sum(1 for o in orders if o["side"] == "SELL")
    lines.append(f"BUY={buy}, SELL={sell}")

    realized = 0.0
    for o in orders:
        if o["side"] == "SELL" and o["price"] is not None:
            realized += float(o["price"]) * float(o["quantity"])
        elif o["side"] == "BUY" and o["price"] is not None:
            realized -= float(o["price"]) * float(o["quantity"])
    lines.append(f"Approx cash PnL (fills basis): {realized:.2f}")

    lines.append(f"Events: {len(events)}")
    for evt in events[:10]:
        lines.append(f"- [{evt['level']}] {evt['ts_utc']} {evt['message']}")
    return "\n".join(lines)
