from __future__ import annotations

import csv
from html import escape
from pathlib import Path


def _to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_grid_summary(path: str | Path) -> list[dict[str, str]]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"grid summary not found: {file_path}")
    with file_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def render_leaderboard_html(rows: list[dict[str, str]], source_path: str | Path) -> str:
    scenarios = sorted({str(r.get("scenario", "")).strip() for r in rows if str(r.get("scenario", "")).strip()})
    scenario_blocks: list[str] = []

    def _build_table(title: str, table_id: str, table_rows_src: list[dict[str, str]], show_scenario_col: bool) -> str:
        table_rows_src.sort(key=lambda r: _to_float(r.get("portfolio_return_pct", "0")), reverse=True)
        table_rows = []
        for i, row in enumerate(table_rows_src, start=1):
            ret = _to_float(row.get("portfolio_return_pct", "0"))
            dd = _to_float(row.get("avg_max_drawdown_pct", "0"))
            pnl = _to_float(row.get("total_pnl", "0"))
            ret_class = "pos" if ret >= 0 else "neg"
            dd_class = "warn" if dd >= 20 else "ok"
            scenario_cell = (
                f"<td>{escape(str(row.get('scenario', '')))}</td>"
                if show_scenario_col
                else ""
            )
            table_rows.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{escape(str(row.get('run_id', '')))}</td>"
                f"{scenario_cell}"
                f"<td>{escape(str(row.get('duration', '')))}</td>"
                f"<td>{escape(str(row.get('bar_size', '')))}</td>"
                f"<td>{escape(str(row.get('total_trades', '')))}</td>"
                f"<td class='{ret_class}'>{ret:.2f}%</td>"
                f"<td>{pnl:.2f}</td>"
                f"<td class='{dd_class}'>{dd:.2f}%</td>"
                f"<td>{escape(str(row.get('overrides', '')))}</td>"
                "</tr>"
            )
        scenario_header = "<th onclick='sortTable(this, 2)'>Scenario</th>" if show_scenario_col else ""
        scenario_col_shift = 1 if show_scenario_col else 0
        duration_col = 2 + scenario_col_shift
        bar_size_col = 3 + scenario_col_shift
        trades_col = 4 + scenario_col_shift
        return_col = 5 + scenario_col_shift
        pnl_col = 6 + scenario_col_shift
        dd_col = 7 + scenario_col_shift
        block = (
            f"<h2>{escape(title)}</h2>"
            f"<table class='grid' data-scenario='{escape(table_id)}'>"
            "<thead><tr>"
            "<th onclick='sortTable(this, 0)'>Rank</th>"
            "<th onclick='sortTable(this, 1)'>Run</th>"
            f"{scenario_header}"
            f"<th onclick='sortTable(this, {duration_col})'>Duration</th>"
            f"<th onclick='sortTable(this, {bar_size_col})'>Bar Size</th>"
            f"<th onclick='sortTable(this, {trades_col})'>Trades</th>"
            f"<th onclick='sortTable(this, {return_col})'>Return %</th>"
            f"<th onclick='sortTable(this, {pnl_col})'>PnL</th>"
            f"<th onclick='sortTable(this, {dd_col})'>Avg MaxDD %</th>"
            "<th>Overrides</th>"
            "</tr></thead>"
            f"<tbody>{''.join(table_rows)}</tbody>"
            "</table>"
        )
        return block

    all_rows = [dict(r) for r in rows]
    scenario_blocks.append(_build_table("All Scenarios", "all", all_rows, show_scenario_col=True))
    for scenario in scenarios:
        scenario_rows = [dict(r) for r in rows if str(r.get("scenario", "")).strip() == scenario]
        scenario_blocks.append(_build_table(scenario, scenario, scenario_rows, show_scenario_col=False))

    source = escape(str(source_path))
    return (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>Backtest Grid Leaderboard</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;color:#111;padding:20px;}"
        "h1{margin:0 0 6px 0;} .meta{color:#555;margin-bottom:20px;}"
        "h2{margin:18px 0 8px 0;} table.grid{border-collapse:collapse;width:100%;background:#fff;}"
        "th,td{border:1px solid #d8deea;padding:6px 8px;font-size:13px;}"
        "th{background:#1f3a5f;color:#fff;cursor:pointer;position:sticky;top:0;}"
        "tr:nth-child(even){background:#f8fbff;} .pos{color:#0a7a28;font-weight:600;}"
        ".neg{color:#b01f1f;font-weight:600;} .warn{color:#b06b00;font-weight:600;} .ok{color:#175f1a;}"
        "</style>"
        "<script>"
        "function parseNum(text){const n=parseFloat(text.replace('%',''));return isNaN(n)?null:n;}"
        "function sortTable(th,col){"
        "const table=th.closest('table');const tbody=table.tBodies[0];"
        "const rows=Array.from(tbody.rows);"
        "const asc=th.dataset.asc!=='1';"
        "rows.sort((a,b)=>{"
        "const av=a.cells[col].innerText.trim(); const bv=b.cells[col].innerText.trim();"
        "const an=parseNum(av); const bn=parseNum(bv);"
        "if(an!==null && bn!==null){return asc?an-bn:bn-an;}"
        "return asc?av.localeCompare(bv):bv.localeCompare(av);});"
        "rows.forEach(r=>tbody.appendChild(r)); th.dataset.asc=asc?'1':'0';"
        "}"
        "</script></head><body>"
        "<h1>Backtest Grid Leaderboard</h1>"
        f"<div class='meta'>Source: {source}</div>"
        f"{''.join(scenario_blocks)}"
        "</body></html>"
    )


def write_leaderboard_html(summary_path: str | Path, output_path: str | Path | None = None) -> Path:
    rows = load_grid_summary(summary_path)
    out = Path(output_path) if output_path else (Path(summary_path).parent / "leaderboard.html")
    html = render_leaderboard_html(rows, summary_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def write_trades_html(trades_csv_path: str | Path, output_path: str | Path | None = None) -> Path:
    csv_path = Path(trades_csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"trades csv not found: {csv_path}")

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
        headers = list(reader.fieldnames or [])

    def _cell_class(header: str, value: str) -> str:
        if header in {"profit_loss_abs", "profit_loss_pct", "cum_profit_loss_abs", "cum_profit_loss_pct"}:
            return "pos" if _to_float(value) >= 0 else "neg"
        if header == "exit_reason" and str(value).upper() == "STOP_LOSS":
            return "warn"
        return ""

    def _render_rows() -> str:
        out_rows: list[str] = []
        for row in rows:
            cols = []
            for h in headers:
                value = str(row.get(h, ""))
                cls = _cell_class(h, value)
                cls_attr = f" class='{cls}'" if cls else ""
                cols.append(f"<td{cls_attr}>{escape(value)}</td>")
            out_rows.append("<tr>" + "".join(cols) + "</tr>")
        return "".join(out_rows)

    header_cells = "".join(
        f"<th onclick='sortTable(this, {idx})'>{escape(h)}</th>" for idx, h in enumerate(headers)
    )
    out = Path(output_path) if output_path else csv_path.with_suffix(".html")
    html = (
        "<!doctype html>"
        "<html><head><meta charset='utf-8'><title>Backtest Trades</title>"
        "<style>"
        "body{font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;color:#111;padding:20px;}"
        "h1{margin:0 0 6px 0;} .meta{color:#555;margin-bottom:20px;}"
        "table.grid{border-collapse:collapse;width:100%;background:#fff;}"
        "th,td{border:1px solid #d8deea;padding:6px 8px;font-size:12px;}"
        "th{background:#1f3a5f;color:#fff;cursor:pointer;position:sticky;top:0;}"
        "tr:nth-child(even){background:#f8fbff;} .pos{color:#0a7a28;font-weight:600;}"
        ".neg{color:#b01f1f;font-weight:600;} .warn{color:#b06b00;font-weight:600;}"
        "</style>"
        "<script>"
        "function parseNum(text){const n=parseFloat(text.replace('%',''));return isNaN(n)?null:n;}"
        "function sortTable(th,col){"
        "const table=th.closest('table');const tbody=table.tBodies[0];"
        "const rows=Array.from(tbody.rows);"
        "const asc=th.dataset.asc!=='1';"
        "rows.sort((a,b)=>{"
        "const av=a.cells[col].innerText.trim(); const bv=b.cells[col].innerText.trim();"
        "const an=parseNum(av); const bn=parseNum(bv);"
        "if(an!==null && bn!==null){return asc?an-bn:bn-an;}"
        "return asc?av.localeCompare(bv):bv.localeCompare(av);});"
        "rows.forEach(r=>tbody.appendChild(r)); th.dataset.asc=asc?'1':'0';"
        "}"
        "</script></head><body>"
        "<h1>Backtest Trades</h1>"
        f"<div class='meta'>Source: {escape(str(csv_path))} | Rows: {len(rows)}</div>"
        "<table class='grid'><thead><tr>"
        f"{header_cells}"
        "</tr></thead><tbody>"
        f"{_render_rows()}"
        "</tbody></table></body></html>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
