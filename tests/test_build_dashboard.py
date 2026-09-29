from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.build_dashboard import build, compute_panels, load_records

START = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)


def _write_logs(path: Path) -> None:
    events = []
    for i, latency in enumerate([100, 200, 3000, 400]):
        ts = START + timedelta(seconds=30 * i)
        events.append({"event": "request_received", "ts": ts.isoformat()})
        events.append(
            {
                "event": "response_sent",
                "ts": ts.isoformat(),
                "latency_ms": latency,
                "ttft_ms": 50,
                "cost_usd": 0.5,
                "tokens_in": 10,
                "tokens_out": 20,
                "quality_score": 0.8,
                "tool_success": True,
            }
        )
    events.append({"event": "request_received", "ts": (START + timedelta(minutes=2)).isoformat()})
    events.append(
        {
            "event": "request_failed",
            "ts": (START + timedelta(minutes=2)).isoformat(),
            "error_type": "RuntimeError",
            "tool_success": False,
        }
    )
    path.write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n", encoding="utf-8")


def test_compute_panels_matches_contract_aggregations(tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    _write_logs(log_path)
    panels = compute_panels(load_records(log_path, START, START + timedelta(hours=1)))

    assert panels["latency"]["stats"]["p95"] == 3000
    assert panels["latency"]["stats"]["ttft_p95"] == 50
    assert panels["traffic"]["stats"]["count"] == 5
    assert panels["errors"]["stats"]["error_rate_pct"] == 20
    assert panels["errors"]["stats"]["count_by_value"] == {"RuntimeError": 1}
    assert panels["errors"]["stats"]["tool_success_rate_pct"] == 80
    assert panels["cost"]["stats"]["total"] == 2.0
    assert panels["tokens"]["stats"]["sum_by_field"] == 120
    assert panels["quality"]["stats"]["mean"] == 0.8


def test_build_writes_six_panels_and_ignores_records_outside_range(tmp_path: Path) -> None:
    log_path, out = tmp_path / "logs.jsonl", tmp_path / "dashboard.html"
    _write_logs(log_path)
    summary = build(Path("config/dashboard.yaml"), log_path, out, START + timedelta(minutes=1))

    page = out.read_text(encoding="utf-8")
    assert page.count('<section class="panel">') == 6
    assert "6 records" in summary  # request_failed ở phút thứ 2 nằm ngoài time range
    assert "errors   error_rate_pct=0.0%" in summary
