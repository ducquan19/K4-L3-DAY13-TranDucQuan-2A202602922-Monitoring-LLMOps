"""Dựng dashboard runtime sáu panel từ data/logs.jsonl theo contract config/dashboard.yaml.

    python scripts/build_dashboard.py              # ghi data/dashboard.html một lần
    python scripts/build_dashboard.py --watch      # dựng lại mỗi refresh_seconds

Mở file HTML bằng trình duyệt; trang tự reload theo refresh_seconds của contract.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from scripts.validate_dashboard import load_dashboard_config

OPERATOR_TEXT = {"lte": "≤", "gte": "≥"}
SERIES_COLORS = ["#2563eb", "#d97706", "#7c3aed", "#059669"]


def load_records(path: Path, start: datetime, end: datetime) -> list[dict]:
    records = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if start <= ts <= end:
            rec["_ts"] = ts
            records.append(rec)
    return records


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    items = sorted(values)
    return float(items[max(0, math.ceil(p / 100 * len(items)) - 1)])


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def by_minute(records: list[dict]) -> dict[datetime, list[dict]]:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for rec in records:
        buckets[rec["_ts"].replace(second=0, microsecond=0)].append(rec)
    return buckets


def compute_panels(records: list[dict]) -> dict[str, dict]:
    """Trả về cho mỗi panel: stats (giá trị toàn cửa sổ) và series (giá trị theo phút)."""
    sent = [r for r in records if r.get("event") == "response_sent"]
    received = [r for r in records if r.get("event") == "request_received"]
    failed = [r for r in records if r.get("event") == "request_failed"]
    tool_events = [r for r in records if r.get("tool_success") is not None]

    minutes = sorted(by_minute(records))
    sent_by_min, recv_by_min, fail_by_min = by_minute(sent), by_minute(received), by_minute(failed)

    def series(buckets, fn):
        return [(m, fn(buckets.get(m, []))) for m in minutes]

    def pct(field, p):
        return lambda rs: percentile([r[field] for r in rs if r.get(field) is not None], p)

    def total(field):
        return lambda rs: sum(r.get(field) or 0 for r in rs) if rs else None

    def error_rate(m):
        n = len(recv_by_min.get(m, []))
        return 100 * len(fail_by_min.get(m, [])) / n if n else None

    span_minutes = max(1.0, (records[-1]["_ts"] - records[0]["_ts"]).total_seconds() / 60) if records else 1.0
    latencies = [r["latency_ms"] for r in sent if r.get("latency_ms") is not None]
    ttfts = [r["ttft_ms"] for r in sent if r.get("ttft_ms") is not None]
    qualities = [r["quality_score"] for r in sent if r.get("quality_score") is not None]

    return {
        "latency": {
            "stats": {
                "p50": percentile(latencies, 50),
                "p95": percentile(latencies, 95),
                "p99": percentile(latencies, 99),
                "ttft_p95": percentile(ttfts, 95),
            },
            "series": {
                "p50": series(sent_by_min, pct("latency_ms", 50)),
                "p95": series(sent_by_min, pct("latency_ms", 95)),
                "p99": series(sent_by_min, pct("latency_ms", 99)),
                "ttft_p95": series(sent_by_min, pct("ttft_ms", 95)),
            },
        },
        "traffic": {
            "stats": {"count": len(received), "rate_per_minute": len(received) / span_minutes},
            "series": {"rate_per_minute": series(recv_by_min, lambda rs: len(rs))},
        },
        "errors": {
            "stats": {
                "error_rate_pct": 100 * len(failed) / len(received) if received else None,
                "count_by_value": dict(Counter(r.get("error_type") or "unknown" for r in failed)) or {"none": 0},
                "tool_success_rate_pct": (
                    100 * sum(1 for r in tool_events if r["tool_success"]) / len(tool_events)
                    if tool_events
                    else None
                ),
            },
            "series": {"error_rate_pct": [(m, error_rate(m)) for m in minutes]},
        },
        "cost": {
            "stats": {"total": sum(r.get("cost_usd") or 0 for r in sent)},
            "series": {"sum_by_minute": series(sent_by_min, total("cost_usd"))},
        },
        "tokens": {
            "stats": {
                "sum_by_field": sum((r.get("tokens_in") or 0) + (r.get("tokens_out") or 0) for r in sent),
                "tokens_in": sum(r.get("tokens_in") or 0 for r in sent),
                "tokens_out": sum(r.get("tokens_out") or 0 for r in sent),
            },
            "series": {
                "tokens_in": series(sent_by_min, total("tokens_in")),
                "tokens_out": series(sent_by_min, total("tokens_out")),
            },
        },
        "quality": {
            "stats": {"mean": mean(qualities)},
            "series": {"mean": series(sent_by_min, lambda rs: mean([r["quality_score"] for r in rs if r.get("quality_score") is not None]))},
        },
    }


def fmt(value, unit: str) -> str:
    if value is None:
        return "–"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if unit == "usd":
        return f"${value:.4f}"
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "score_0_to_1":
        return f"{value:.2f}"
    if unit == "requests_per_minute":
        return f"{value:.1f}/min"
    if unit == "ms":
        return f"{value:.0f} ms"
    return f"{value:,.0f}"


def breached(value, threshold: dict) -> bool | None:
    if not isinstance(value, (int, float)):
        return None
    return value > threshold["value"] if threshold["operator"] == "lte" else value < threshold["value"]


def svg_chart(series: dict[str, list], threshold: dict | None, start: datetime, end: datetime, unit: str) -> str:
    width, height, left, right, top, bottom = 560, 190, 56, 12, 12, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for pts in series.values() for _, v in pts if v is not None]
    y_max = max(values + ([threshold["value"]] if threshold else []) + [1e-9]) * 1.15
    span = (end - start).total_seconds()

    def x(ts):
        return left + plot_w * (ts - start).total_seconds() / span

    def y(v):
        return top + plot_h * (1 - v / y_max)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for i in range(5):
        v = y_max * i / 4
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>')
        label = fmt(v, unit).replace(" ms", "").replace("/min", "")
        parts.append(f'<text x="{left - 6}" y="{y(v) + 4:.1f}" class="axis" text-anchor="end">{html.escape(label)}</text>')
    for i in range(7):
        ts = start + timedelta(seconds=span * i / 6)
        local = ts.astimezone().strftime("%H:%M")
        parts.append(f'<text x="{x(ts):.1f}" y="{height - 6}" class="axis" text-anchor="middle">{local}</text>')
    if threshold:
        ty = y(threshold["value"])
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{ty:.1f}" y2="{ty:.1f}" class="threshold"/>')
        label = f'{threshold["aggregation"]} {OPERATOR_TEXT[threshold["operator"]]} {threshold["value"]}'
        parts.append(f'<text x="{width - right - 4}" y="{ty - 4:.1f}" class="threshold-label" text-anchor="end">{html.escape(label)}</text>')
    for color, (name, pts) in zip(SERIES_COLORS, series.items()):
        pts = [(ts, v) for ts, v in pts if v is not None]
        coords = " ".join(f"{x(ts + timedelta(seconds=30)):.1f},{y(v):.1f}" for ts, v in pts)
        if len(pts) > 1:
            parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
        for ts, v in pts:
            tip = f"{name} {ts.astimezone():%H:%M}: {fmt(v, unit)}"
            parts.append(
                f'<circle cx="{x(ts + timedelta(seconds=30)):.1f}" cy="{y(v):.1f}" r="3" fill="{color}"><title>{html.escape(tip)}</title></circle>'
            )
    parts.append("</svg>")
    legend = "".join(
        f'<span class="key"><i style="background:{c}"></i>{html.escape(n)}</span>'
        for c, n in zip(SERIES_COLORS, series)
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def render(config: dict, panels: dict, start: datetime, end: datetime, record_count: int, log_path: Path) -> str:
    dash = config["dashboard"]
    cards = []
    for panel in dash["panels"]:
        data = panels[panel["id"]]
        threshold = panel["threshold"]
        unit = panel["unit"]
        headline = data["stats"].get(threshold["aggregation"])
        status = breached(headline, threshold)
        badge = {None: ("no data", "muted"), True: ("BREACH", "bad"), False: ("OK", "good")}[status]
        stats = "".join(
            f'<div class="stat"><span>{html.escape(k)}</span><b>{html.escape(fmt(v, unit if k not in ("count", "tokens_in", "tokens_out", "count_by_value") else "count"))}</b></div>'
            for k, v in data["stats"].items()
        )
        # Threshold line chỉ vẽ khi nó cùng thang đo với series; ngưỡng trên tổng cả cửa sổ (cost, tokens)
        # không so được với giá trị theo phút nên thể hiện bằng badge.
        line = threshold if threshold["aggregation"] in data["series"] else None
        cards.append(
            f"""<section class="panel">
  <header><h2>{html.escape(panel["title"])}</h2><span class="badge {badge[1]}">{badge[0]}</span></header>
  <p class="meta">unit: <b>{html.escape(unit)}</b> · threshold: <b>{html.escape(threshold["aggregation"])} {OPERATOR_TEXT[threshold["operator"]]} {threshold["value"]}</b> · events: {html.escape(", ".join(panel["events"]))}</p>
  <div class="stats">{stats}</div>
  {svg_chart(data["series"], line, start, end, unit)}
  <p class="query"><code>{html.escape(panel["query"])}</code></p>
</section>"""
        )

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{dash["refresh_seconds"]}">
<title>{html.escape(dash["title"])}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#111827; --muted:#6b7280; --line:#e5e7eb; --bad:#dc2626; --good:#059669; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1115; --card:#181b21; --fg:#e5e7eb; --muted:#9ca3af; --line:#2a2f38; --bad:#f87171; --good:#34d399; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui, sans-serif; }}
.top {{ padding:16px 20px; border-bottom:1px solid var(--line); display:flex; flex-wrap:wrap; gap:6px 20px; align-items:baseline; }}
.top h1 {{ font-size:18px; margin:0; }} .top span {{ color:var(--muted); }}
main {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr)); gap:16px; padding:16px 20px; }}
.panel {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; min-width:0; }}
.panel header {{ display:flex; justify-content:space-between; align-items:center; }}
h2 {{ font-size:15px; margin:0; }}
.badge {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:99px; border:1px solid currentColor; }}
.badge.bad {{ color:var(--bad); }} .badge.good {{ color:var(--good); }} .badge.muted {{ color:var(--muted); }}
.meta, .query {{ color:var(--muted); font-size:12px; margin:4px 0 8px; }} .query code {{ white-space:pre-wrap; word-break:break-word; }}
.stats {{ display:flex; flex-wrap:wrap; gap:6px 18px; margin-bottom:6px; }}
.stat span {{ display:block; color:var(--muted); font-size:11px; }} .stat b {{ font-size:15px; font-variant-numeric:tabular-nums; }}
.legend {{ display:flex; gap:12px; font-size:12px; color:var(--muted); }} .key i {{ display:inline-block; width:10px; height:3px; margin-right:4px; vertical-align:middle; }}
.chart {{ width:100%; height:auto; }} .grid {{ stroke:var(--line); }} .axis {{ fill:var(--muted); font-size:10px; }}
.threshold {{ stroke:var(--bad); stroke-dasharray:5 4; stroke-width:1.5; }} .threshold-label {{ fill:var(--bad); font-size:10px; }}
@media (max-width:480px) {{ main {{ grid-template-columns:1fr; padding:12px 16px; }} }}
</style></head>
<body>
<div class="top"><h1>{html.escape(dash["title"])}</h1>
<span>time range: last {dash["time_range_minutes"]} min ({start.astimezone():%Y-%m-%d %H:%M} → {end.astimezone():%H:%M %z})</span>
<span>refresh: {dash["refresh_seconds"]}s</span><span>source: {html.escape(str(log_path.as_posix()))} ({record_count} records)</span></div>
<main>{"".join(cards)}</main>
</body></html>"""


def build(config_path: Path, log_path: Path, out_path: Path, end: datetime | None) -> str:
    config = load_dashboard_config(config_path)
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(minutes=config["dashboard"]["time_range_minutes"])
    records = load_records(log_path, start, end)
    panels = compute_panels(records)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(config, panels, start, end, len(records), log_path), encoding="utf-8")
    lines = [f"{out_path} | {len(records)} records | {start.astimezone():%H:%M}–{end.astimezone():%H:%M}"]
    for panel in config["dashboard"]["panels"]:
        th = panel["threshold"]
        value = panels[panel["id"]]["stats"].get(th["aggregation"])
        state = {None: "no data", True: "BREACH", False: "OK"}[breached(value, th)]
        lines.append(f"  {panel['id']:<8} {th['aggregation']}={fmt(value, panel['unit'])} ({OPERATOR_TEXT[th['operator']]} {th['value']}) {state}")
    return "\n".join(lines)


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=Path("data/logs.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("data/dashboard.html"))
    parser.add_argument("--end", help="Mốc cuối time range (ISO 8601), mặc định là hiện tại")
    parser.add_argument("--watch", action="store_true", help="Dựng lại theo refresh_seconds")
    args = parser.parse_args()
    end = datetime.fromisoformat(args.end).astimezone(timezone.utc) if args.end else None

    while True:
        print(build(args.config, args.logs, args.out, end))
        if not args.watch:
            return
        time.sleep(load_dashboard_config(args.config)["dashboard"]["refresh_seconds"])


if __name__ == "__main__":
    main()
