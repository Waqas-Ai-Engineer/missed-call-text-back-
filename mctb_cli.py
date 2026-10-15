"""Command-line interface: ``mctb plan|demo|templates|serve``."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

__version__ = "0.1.0"
from mctb_core import Config, PlannedText, Skipped, fmt_time, parse_calls, plan, summarize
from mctb_templates import INDUSTRIES

EXAMPLES = Path(__file__).resolve().parent
DEMO_NOW = "2026-10-15T07:05:00"


def load_config(path: Optional[str]) -> Config:
    """Load a JSON config file (or defaults)."""
    if not path:
        return Config()
    return Config.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def render_table(planned: List[PlannedText], skipped: List[Skipped], summary: dict) -> str:
    """Human-readable report."""
    lines = ["MISSED-CALL TEXT-BACK PLAN", "=" * 26, ""]
    for i, p in enumerate(planned, 1):
        tag = "URGENT" if p.urgent else ("closed-msg" if not p.business_open_at_send else "open-msg")
        who = p.name or "(no name)"
        lines.append(f"{i:>2}. {p.phone}  {who}  [{tag}]  calls={p.missed_count}  send={fmt_time(p.send_at)}")
        lines.append(f"    why: {p.reason}")
        lines.append(f"    sms ({len(p.message)} chars, {p.segments} segment): {p.message}")
        lines.append("")
    lines.append("SUMMARY")
    lines.append(f"  texts to send : {summary['texts_to_send']} (urgent {summary['urgent']}, "
                 f"closed-msg {summary['after_hours']}, repeat callers {summary['repeat_callers']})")
    lines.append("  skipped       : " + (", ".join(f"{k}={v}" for k, v in summary["skipped"].items()) or "none"))
    if "estimated_recoverable_revenue" in summary:
        lines.append(f"  est. revenue  : {summary['estimated_recoverable_revenue']:,.0f}  <- {summary['estimate_assumptions']}")
    return "\n".join(lines)


def render_csv(planned: List[PlannedText]) -> str:
    """CSV export, ready to paste into a sheet or an SMS tool."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["phone", "name", "send_at", "urgent", "missed_count", "segments", "message"])
    for p in planned:
        w.writerow([p.phone, p.name, p.send_at.isoformat(), p.urgent, p.missed_count, p.segments, p.message])
    return buf.getvalue()


def render_json(planned: List[PlannedText], skipped: List[Skipped], summary: dict) -> str:
    """JSON export for pipelines (n8n, Zapier, scripts)."""
    def row(p: PlannedText) -> dict:
        return {"phone": p.phone, "name": p.name, "first_call_at": p.first_call_at.isoformat(),
                "send_at": p.send_at.isoformat(), "urgent": p.urgent, "missed_count": p.missed_count,
                "priority": p.priority, "segments": p.segments, "reason": p.reason, "message": p.message}
    return json.dumps({"summary": summary, "texts": [row(p) for p in planned],
                       "skipped": [{"phone": s.phone, "when": s.when.isoformat(), "reason": s.reason}
                                   for s in skipped]}, indent=2)


def _run_plan(csv_path: str, cfg: Config, now_str: Optional[str], fmt: str) -> int:
    text = Path(csv_path).read_text(encoding="utf-8-sig")
    now = datetime.fromisoformat(now_str).replace(tzinfo=cfg.tz) if now_str else datetime.now(cfg.tz)
    planned, skipped = plan(parse_calls(text, cfg), cfg, now)
    summary = summarize(planned, skipped, cfg)
    if fmt == "json":
        print(render_json(planned, skipped, summary))
    elif fmt == "csv":
        print(render_csv(planned), end="")
    else:
        print(render_table(planned, skipped, summary))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    p = argparse.ArgumentParser(prog="mctb", description="Plan instant text-backs for missed calls "
                                "(offline, no API keys needed for planning).")
    p.add_argument("--version", action="version", version=f"mctb {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="plan text-backs from a call-log CSV")
    pl.add_argument("calls_csv")
    pl.add_argument("-c", "--config", help="JSON config (see example_config.json)")
    pl.add_argument("--now", help="ISO time to treat as 'now' (default: current time)")
    pl.add_argument("-f", "--format", choices=["table", "json", "csv"], default="table")
    sub.add_parser("demo", help="run on the bundled SAMPLE data (fictional numbers)")
    sub.add_parser("templates", help="list built-in industries")
    sv = sub.add_parser("serve", help="Twilio-compatible webhook (dry-run unless --send)")
    sv.add_argument("-c", "--config")
    sv.add_argument("--port", type=int, default=8080)
    sv.add_argument("--send", action="store_true", help="really send SMS via Twilio (needs env vars)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    if args.cmd == "templates":
        print("\n".join(sorted(INDUSTRIES)))
        return 0
    if args.cmd == "demo":
        cfg = load_config(str(EXAMPLES / "example_config.json"))
        print("(SAMPLE DATA - fictional numbers and business)\n")
        return _run_plan(str(EXAMPLES / "example_calls.csv"), cfg, DEMO_NOW, "table")
    if args.cmd == "plan":
        return _run_plan(args.calls_csv, load_config(args.config), args.now, args.format)
    if args.cmd == "serve":
        from mctb_webhook import serve
        serve(load_config(args.config), args.port, args.send)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
