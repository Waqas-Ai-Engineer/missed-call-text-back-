import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mctb_core import (Config, is_open, in_quiet_hours, next_open, normalize_phone,  # noqa: E402
                                        parse_calls, plan, sms_segments, summarize)
from mctb_webhook import handle_status, twilio_signature  # noqa: E402

TZ = timezone(timedelta(hours=-5))
CFG = Config(business_name="Test Co", utc_offset_hours=-5, avg_job_value=100)


def calls(csv_body):
    return parse_calls("timestamp,caller,status,name,voicemail,direction\n" + csv_body, CFG)


def now(s):
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


class PhoneTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(normalize_phone("(555) 010-0101"), "+15550100101")
        self.assertEqual(normalize_phone("+44 20 7946 0958"), "+442079460958")
        self.assertEqual(normalize_phone("15550100101"), "+15550100101")
        self.assertIsNone(normalize_phone("12345"))
        self.assertIsNone(normalize_phone(""))


class HoursTests(unittest.TestCase):
    def test_open_closed_next(self):
        thu_10 = now("2026-10-15T10:00")
        sat_10 = now("2026-10-17T10:00")
        self.assertTrue(is_open(thu_10, CFG))
        self.assertFalse(is_open(sat_10, CFG))
        self.assertEqual(next_open(sat_10, CFG).strftime("%a %H:%M"), "Mon 08:00")

    def test_quiet_overnight(self):
        self.assertTrue(in_quiet_hours(now("2026-10-15T23:00"), CFG))
        self.assertTrue(in_quiet_hours(now("2026-10-15T06:00"), CFG))
        self.assertFalse(in_quiet_hours(now("2026-10-15T12:00"), CFG))


class PlanTests(unittest.TestCase):
    def test_dedupe_merges_repeat_calls(self):
        c = calls("2026-10-15 09:00,+15550100101,missed,,,inbound\n2026-10-15 09:20,+15550100101,missed,,,inbound")
        texts, skipped = plan(c, CFG, now("2026-10-15T09:30"))
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].missed_count, 2)
        self.assertEqual([s.reason for s in skipped], ["duplicate_within_window"])

    def test_callback_recovers_lead(self):
        c = calls("2026-10-15 09:00,+15550100101,missed,,,inbound\n2026-10-15 09:30,+15550100101,answered,,,outbound")
        texts, skipped = plan(c, CFG, now("2026-10-15T10:00"))
        self.assertEqual(texts, [])
        self.assertEqual(skipped[0].reason, "already_reached")

    def test_blocklists_and_age(self):
        cfg = Config(utc_offset_hours=-5, do_not_text=["+15550100102"], internal_numbers=["+15550100103"])
        c = parse_calls(
            "timestamp,caller,status\n2026-10-15 09:00,+15550100102,missed\n"
            "2026-10-15 09:00,+15550100103,missed\n2026-10-01 09:00,+15550100104,missed\n"
            "2026-10-15 09:00,999,missed", cfg)
        texts, skipped = plan(c, cfg, now("2026-10-15T10:00"))
        self.assertEqual(texts, [])
        self.assertEqual(sorted(s.reason for s in skipped),
                         ["do_not_text", "internal_number", "invalid_number", "too_old"])

    def test_quiet_hours_delay_and_urgent_bypass(self):
        c = calls("2026-10-14 22:15,+15550100105,missed,,,inbound\n"
                  "2026-10-14 22:20,+15550100106,voicemail,,burst pipe flooding,inbound")
        texts, _ = plan(c, CFG, now("2026-10-15T06:00"))
        by = {t.phone: t for t in texts}
        self.assertEqual(by["+15550100105"].send_at.strftime("%H:%M"), "08:00")
        self.assertTrue(by["+15550100106"].urgent)
        self.assertEqual(by["+15550100106"].send_at.strftime("%H:%M"), "06:00")
        self.assertEqual(texts[0].phone, "+15550100106")  # urgent sorts first

    def test_message_content(self):
        c = calls("2026-10-15 18:00,+15550100101,missed,Sam,,inbound")
        texts, _ = plan(c, CFG, now("2026-10-15T18:01"))
        m = texts[0].message
        self.assertTrue(m.startswith("Hi Sam, this is Test Co."))
        self.assertIn("reopen Fri 8:00 AM", m)
        self.assertTrue(m.endswith("Reply STOP to opt out."))
        self.assertLessEqual(texts[0].segments, 2)

    def test_summary_estimate_is_labelled(self):
        c = calls("2026-10-15 09:00,+15550100101,missed,,,inbound")
        texts, skipped = plan(c, CFG, now("2026-10-15T09:10"))
        s = summarize(texts, skipped, CFG)
        self.assertEqual(s["estimated_recoverable_revenue"], 15.0)
        self.assertIn("your inputs", s["estimate_assumptions"])

    def test_segments(self):
        self.assertEqual(sms_segments("a" * 160), 1)
        self.assertEqual(sms_segments("a" * 161), 2)


class WebhookTests(unittest.TestCase):
    def test_signature_matches_twilio_docs_algorithm(self):
        sig = twilio_signature("token", "https://x.test/hook", {"b": "2", "a": "1"})
        self.assertEqual(sig, twilio_signature("token", "https://x.test/hook", {"a": "1", "b": "2"}))
        self.assertNotEqual(sig, twilio_signature("other", "https://x.test/hook", {"a": "1", "b": "2"}))

    def test_status_handling_and_dedupe(self):
        state = {}
        n = now("2026-10-15T10:00")
        p = {"CallStatus": "no-answer", "From": "+15550100101"}
        self.assertEqual(handle_status(p, CFG, state, n)["action"], "send")
        self.assertEqual(handle_status(p, CFG, state, n + timedelta(hours=1))["reason"], "duplicate_within_window")
        self.assertEqual(handle_status({"CallStatus": "completed", "From": "+15550100101"}, CFG, state, n)["action"], "ignore")


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "mctb.py", *args], cwd=ROOT,
                              capture_output=True, text=True)

    def test_demo(self):
        r = self.run_cli("demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SAMPLE DATA", r.stdout)
        self.assertIn("URGENT", r.stdout)

    def test_json_output(self):
        r = self.run_cli("plan", "example_calls.csv", "-c", "example_config.json",
                         "--now", "2026-10-15T07:05:00", "-f", "json")
        data = json.loads(r.stdout)
        self.assertEqual(data["summary"]["texts_to_send"], len(data["texts"]))
        self.assertGreater(data["summary"]["texts_to_send"], 0)

    def test_help(self):
        self.assertEqual(self.run_cli("--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
