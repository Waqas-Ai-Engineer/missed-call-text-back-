"""Optional Twilio-compatible webhook. Dry-run by default; sends only with --send + env vars."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from mctb_core import Call, Config, MISSED_STATUSES, normalize_phone, plan

TWILIO_MISSED = {"no-answer", "busy", "failed", "canceled"}


def twilio_signature(auth_token: str, url: str, params: Dict[str, str]) -> str:
    """Compute Twilio's X-Twilio-Signature (HMAC-SHA1 of URL + sorted key/value pairs)."""
    data = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def handle_status(params: Dict[str, str], cfg: Config, state: Dict[str, datetime],
                  now: datetime) -> Dict[str, Any]:
    """Decide what to do for one Twilio call-status callback. ``state`` maps phone -> last text time."""
    status = params.get("CallStatus", "").lower()
    phone = normalize_phone(params.get("From", ""), cfg.default_country_code)
    if status not in TWILIO_MISSED or not phone:
        return {"action": "ignore", "reason": f"status={status!r} phone_ok={bool(phone)}"}
    last = state.get(phone)
    if last and (now - last).total_seconds() < cfg.dedupe_hours * 3600:
        return {"action": "skip", "reason": "duplicate_within_window", "to": phone}
    call = Call(when=now, caller_raw=params.get("From", ""), caller=phone, status="missed",
                name=params.get("CallerName", ""))
    texts, skipped = plan([call], cfg, now)
    if not texts:
        return {"action": "skip", "reason": skipped[0].reason if skipped else "no_plan", "to": phone}
    t = texts[0]
    state[phone] = now
    return {"action": "send", "to": phone, "message": t.message, "send_at": t.send_at.isoformat(),
            "segments": t.segments}


def send_sms(to: str, body: str, from_number: str, sid: str, token: str) -> int:
    """Send one SMS through Twilio's REST API. Returns the HTTP status code."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({"To": to, "From": from_number, "Body": body}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - fixed https host
        return resp.status


def make_handler(cfg: Config, send: bool):
    """Create a request-handler class bound to ``cfg``."""
    state: Dict[str, datetime] = {}
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    from_number = os.environ.get("TWILIO_FROM", "")
    public_url = os.environ.get("MCTB_PUBLIC_URL", "")

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._json(200, {"ok": True, "mode": "send" if send else "dry-run"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode()
            params = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
            if send and token:
                sig = self.headers.get("X-Twilio-Signature", "")
                if not hmac.compare_digest(sig, twilio_signature(token, public_url, params)):
                    self._json(403, {"error": "bad signature"})
                    return
            result = handle_status(params, cfg, state, datetime.now(cfg.tz))
            if send and result["action"] == "send":
                if not (sid and token and from_number):
                    self._json(500, {"error": "set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM"})
                    return
                result["twilio_http_status"] = send_sms(result["to"], result["message"], from_number, sid, token)
            self._json(200, result)

        def log_message(self, fmt: str, *args: Any) -> None:
            print("[mctb] " + fmt % args)

    return Handler


def serve(cfg: Config, port: int, send: bool) -> None:
    """Run the webhook server until interrupted."""
    srv = HTTPServer(("127.0.0.1", port), make_handler(cfg, send))
    print(f"[mctb] listening on http://127.0.0.1:{port}  mode={'SEND' if send else 'dry-run'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[mctb] stopped")
