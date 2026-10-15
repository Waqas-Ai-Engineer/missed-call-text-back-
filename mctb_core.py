"""Planning engine: turn a call log into a de-duplicated, time-aware list of text-back SMS.

Pure standard library. No network access. All functions are deterministic given ``now``.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field, fields
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from mctb_templates import OPT_OUT, get_templates

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MISSED_STATUSES = {"missed", "no-answer", "noanswer", "busy", "voicemail", "failed", "canceled", "unanswered"}
ANSWERED_STATUSES = {"answered", "completed", "in-progress", "connected"}
DEFAULT_URGENT = [
    "emergency", "urgent", "asap", "flood", "leak", "burst", "no heat", "no hot water",
    "no ac", "gas smell", "smoke", "fire", "sewage", "roof leak", "collapsed", "chest pain",
]


def default_hours() -> Dict[str, Optional[List[str]]]:
    """Mon-Fri 08:00-17:00, weekends closed."""
    return {d: (["08:00", "17:00"] if i < 5 else None) for i, d in enumerate(DAYS)}


@dataclass
class Config:
    """Business settings. Every field is optional; see example_config.json."""

    business_name: str = "Our Team"
    industry: str = "general"
    utc_offset_hours: float = 0.0
    default_country_code: str = "1"
    hours: Dict[str, Optional[List[str]]] = field(default_factory=default_hours)
    quiet_start: str = "21:00"
    quiet_end: str = "08:00"
    urgent_ignores_quiet_hours: bool = True
    send_delay_seconds: int = 30
    dedupe_hours: int = 24
    recover_window_minutes: int = 120
    max_age_hours: int = 48
    booking_link: str = ""
    append_opt_out: bool = True
    do_not_text: List[str] = field(default_factory=list)
    internal_numbers: List[str] = field(default_factory=list)
    urgent_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_URGENT))
    avg_job_value: float = 0.0
    assumed_recovery_rate: float = 0.15

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Build a Config from a dict, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def tz(self) -> timezone:
        return timezone(timedelta(hours=self.utc_offset_hours))


@dataclass
class Call:
    """One row of the call log."""

    when: datetime
    caller_raw: str
    caller: Optional[str]
    status: str
    name: str = ""
    voicemail: str = ""
    direction: str = "inbound"


@dataclass
class PlannedText:
    """One SMS the tool recommends sending."""

    phone: str
    name: str
    first_call_at: datetime
    missed_count: int
    send_at: datetime
    business_open_at_send: bool
    urgent: bool
    priority: int
    message: str
    segments: int
    reason: str


@dataclass
class Skipped:
    """A missed call that gets no text, with the reason."""

    phone: str
    when: datetime
    reason: str


def normalize_phone(raw: str, default_cc: str = "1") -> Optional[str]:
    """Normalize a phone number to E.164 (+15551234567). Returns None if it looks invalid."""
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if raw.startswith("+"):
        out = digits
    elif raw.startswith("00"):
        out = digits[2:]
    elif len(digits) == 10:
        out = default_cc + digits
    elif len(digits) == 11 and digits.startswith(default_cc):
        out = digits
    else:
        return None
    if not 8 <= len(out) <= 15:
        return None
    return "+" + out


def _parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")
    return time(int(hh), int(mm))


def is_open(dt: datetime, cfg: Config) -> bool:
    """True if the business is open at ``dt`` (a timezone-aware local datetime)."""
    span = cfg.hours.get(DAYS[dt.weekday()])
    if not span:
        return False
    return _parse_hhmm(span[0]) <= dt.timetz().replace(tzinfo=None) < _parse_hhmm(span[1])


def next_open(dt: datetime, cfg: Config) -> Optional[datetime]:
    """Next opening time strictly after ``dt`` (None if the week has no open hours)."""
    for i in range(0, 8):
        day = dt.date() + timedelta(days=i)
        span = cfg.hours.get(DAYS[day.weekday()])
        if not span:
            continue
        cand = datetime.combine(day, _parse_hhmm(span[0]), tzinfo=dt.tzinfo)
        if cand > dt:
            return cand
    return None


def in_quiet_hours(dt: datetime, cfg: Config) -> bool:
    """True if ``dt`` falls inside the do-not-text window (handles overnight windows)."""
    t = dt.timetz().replace(tzinfo=None)
    qs, qe = _parse_hhmm(cfg.quiet_start), _parse_hhmm(cfg.quiet_end)
    if qs == qe:
        return False
    return (t >= qs or t < qe) if qs > qe else (qs <= t < qe)


def next_quiet_end(dt: datetime, cfg: Config) -> datetime:
    """The next moment quiet hours end, at or after ``dt``."""
    cand = datetime.combine(dt.date(), _parse_hhmm(cfg.quiet_end), tzinfo=dt.tzinfo)
    return cand if cand > dt else cand + timedelta(days=1)


def fmt_time(dt: datetime) -> str:
    """Friendly time like 'Thu 8:00 AM'."""
    return f"{dt:%a} {dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def sms_segments(text: str) -> int:
    """Approximate number of SMS segments (GSM-7: 160 single, 153 per concatenated part)."""
    return 1 if len(text) <= 160 else math.ceil(len(text) / 153)


def _parse_dt(value: str, cfg: Config) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=cfg.tz)
    return dt.astimezone(cfg.tz)


def parse_calls(text: str, cfg: Config) -> List[Call]:
    """Parse a call-log CSV. Flexible headers: timestamp/time/date, caller/from/phone, status."""
    reader = csv.DictReader(io.StringIO(text))
    calls: List[Call] = []
    for row in reader:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        ts = r.get("timestamp") or r.get("time") or r.get("date") or r.get("datetime")
        raw = r.get("caller") or r.get("from") or r.get("phone") or r.get("number") or ""
        status = (r.get("status") or r.get("call_status") or "").lower()
        if not ts or not status:
            continue
        calls.append(
            Call(
                when=_parse_dt(ts, cfg),
                caller_raw=raw,
                caller=normalize_phone(raw, cfg.default_country_code),
                status=status,
                name=r.get("name", ""),
                voicemail=r.get("voicemail") or r.get("transcript") or r.get("message") or "",
                direction=(r.get("direction") or "inbound").lower(),
            )
        )
    return calls


def is_urgent(text: str, cfg: Config) -> bool:
    """True if the voicemail/transcript contains an urgent keyword."""
    low = text.lower()
    return any(k.lower() in low for k in cfg.urgent_keywords)


def render_message(cfg: Config, kind: str, name: str, reopens: Optional[datetime]) -> str:
    """Render the SMS body for kind in {'open', 'closed', 'urgent'}."""
    tpl = get_templates(cfg.industry)[kind]
    first = name.split()[0] if name.strip() else ""
    ctx = {
        "greeting": f"Hi {first}" if first else "Hi",
        "business": cfg.business_name,
        "reopens": fmt_time(reopens) if reopens else "soon",
        "book": f" Book online: {cfg.booking_link}" if cfg.booking_link else "",
    }
    body = tpl.format(**ctx)
    return body + (OPT_OUT if cfg.append_opt_out else "")


def _schedule(call_time: datetime, now: datetime, urgent: bool, cfg: Config) -> datetime:
    """Earliest sensible send time: call + delay, never in the past, respecting quiet hours."""
    send = max(call_time + timedelta(seconds=cfg.send_delay_seconds), now)
    if in_quiet_hours(send, cfg) and not (urgent and cfg.urgent_ignores_quiet_hours):
        send = next_quiet_end(send, cfg)
    return send


def plan(calls: Iterable[Call], cfg: Config, now: datetime) -> Tuple[List[PlannedText], List[Skipped]]:
    """Build the text-back plan. Returns (texts sorted by priority, skipped calls)."""
    now = now.astimezone(cfg.tz)
    block = {normalize_phone(n, cfg.default_country_code) for n in cfg.do_not_text}
    internal = {normalize_phone(n, cfg.default_country_code) for n in cfg.internal_numbers}
    by_caller: Dict[str, List[Call]] = defaultdict(list)
    skipped: List[Skipped] = []
    for c in sorted(calls, key=lambda c: c.when):
        if c.caller is None:
            if c.status in MISSED_STATUSES:
                skipped.append(Skipped(c.caller_raw or "(blank)", c.when, "invalid_number"))
            continue
        by_caller[c.caller].append(c)

    planned: List[PlannedText] = []
    window = timedelta(minutes=cfg.recover_window_minutes)
    for phone, lst in by_caller.items():
        eligible: List[Call] = []
        for i, c in enumerate(lst):
            if c.direction == "outbound" or c.status not in MISSED_STATUSES:
                continue
            if phone in block:
                skipped.append(Skipped(phone, c.when, "do_not_text"))
            elif phone in internal:
                skipped.append(Skipped(phone, c.when, "internal_number"))
            elif c.when < now - timedelta(hours=cfg.max_age_hours):
                skipped.append(Skipped(phone, c.when, "too_old"))
            elif any(o.status in ANSWERED_STATUSES and c.when < o.when <= c.when + window for o in lst[i + 1:]):
                skipped.append(Skipped(phone, c.when, "already_reached"))
            else:
                eligible.append(c)
        clusters: List[List[Call]] = []
        for c in eligible:
            if clusters and c.when - clusters[-1][0].when < timedelta(hours=cfg.dedupe_hours):
                clusters[-1].append(c)
                skipped.append(Skipped(phone, c.when, "duplicate_within_window"))
            else:
                clusters.append([c])
        for cl in clusters:
            first = cl[0]
            vm = " ".join(c.voicemail for c in cl if c.voicemail)
            name = next((c.name for c in cl if c.name), "")
            urgent = is_urgent(vm, cfg)
            send_at = _schedule(first.when, now, urgent, cfg)
            open_now = is_open(send_at, cfg)
            kind = "urgent" if urgent else ("open" if open_now else "closed")
            msg = render_message(cfg, kind, name, None if open_now else next_open(send_at, cfg))
            prio = (100 if urgent else 0) + (30 if len(cl) > 1 else 0) + (10 if vm else 0) + (5 if open_now else 0)
            reason = "urgent keyword in voicemail" if urgent else (
                "missed during open hours" if is_open(first.when, cfg) else "missed while closed")
            if len(cl) > 1:
                reason += f"; {len(cl)} calls merged"
            planned.append(PlannedText(phone, name, first.when, len(cl), send_at, open_now, urgent, prio,
                                       msg, sms_segments(msg), reason))
    planned.sort(key=lambda p: (-p.priority, p.first_call_at))
    return planned, skipped


def summarize(planned: List[PlannedText], skipped: List[Skipped], cfg: Config) -> Dict[str, Any]:
    """Counts plus an assumption-based revenue estimate (only if avg_job_value is set)."""
    reasons: Dict[str, int] = defaultdict(int)
    for s in skipped:
        reasons[s.reason] += 1
    out: Dict[str, Any] = {
        "texts_to_send": len(planned),
        "urgent": sum(p.urgent for p in planned),
        "after_hours": sum(not p.business_open_at_send for p in planned),
        "repeat_callers": sum(p.missed_count > 1 for p in planned),
        "skipped": dict(sorted(reasons.items())),
    }
    if cfg.avg_job_value > 0:
        out["estimated_recoverable_revenue"] = round(
            len(planned) * cfg.assumed_recovery_rate * cfg.avg_job_value, 2)
        out["estimate_assumptions"] = (
            f"{len(planned)} texts x {cfg.assumed_recovery_rate:.0%} assumed recovery x "
            f"{cfg.avg_job_value:,.0f} avg job value (your inputs, not a measured result)"
        )
    return out
