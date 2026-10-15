"""Built-in SMS templates per industry. ASCII only so messages stay in GSM-7 segments."""

from __future__ import annotations

from typing import Dict

URGENT = (
    "{greeting}, this is {business}. We got your message and it sounds urgent. "
    "Reply with your address and one line about the problem so we can prioritize you. "
    "If anyone is in danger, call your local emergency number."
)

GENERIC: Dict[str, str] = {
    "open": (
        "{greeting}, this is {business}. Sorry we missed your call! "
        "How can we help? Reply here and we will get right back to you.{book}"
    ),
    "closed": (
        "{greeting}, this is {business}. Sorry we missed your call - we are closed now "
        "and reopen {reopens}. Tell us what you need and we will reply first thing.{book}"
    ),
    "urgent": URGENT,
}

INDUSTRIES: Dict[str, Dict[str, str]] = {
    "general": GENERIC,
    "hvac": {
        "open": (
            "{greeting}, this is {business}. Sorry we missed your call! "
            "Heating, cooling or tune-up? Reply here and we will get right back to you.{book}"
        ),
        "closed": (
            "{greeting}, this is {business}. Sorry we missed your call - we reopen {reopens}. "
            "Reply with your issue (no heat, no AC, noise, tune-up) and we will call first thing.{book}"
        ),
        "urgent": URGENT,
    },
    "plumbing": {
        "open": (
            "{greeting}, this is {business}. Sorry we missed you! "
            "Leak, clog or install? Reply here and we will get right back to you.{book}"
        ),
        "closed": (
            "{greeting}, this is {business}. Sorry we missed your call - we reopen {reopens}. "
            "Reply with what is going on and we will call you first thing.{book}"
        ),
        "urgent": URGENT,
    },
    "roofing": {
        "open": (
            "{greeting}, this is {business}. Sorry we missed your call! "
            "Repair, replacement or storm damage? Reply here for a free estimate time.{book}"
        ),
        "closed": (
            "{greeting}, this is {business}. Sorry we missed your call - we reopen {reopens}. "
            "Reply with your address and what you need and we will follow up first thing.{book}"
        ),
        "urgent": URGENT,
    },
    "clinic": {
        "open": (
            "{greeting}, this is {business}. Sorry we missed your call! "
            "Reply here to book or change an appointment and we will get back to you.{book}"
        ),
        "closed": (
            "{greeting}, this is {business}. Our office is closed and reopens {reopens}. "
            "Reply with how we can help (appointment, question) and we will respond then.{book}"
        ),
        "urgent": URGENT,
    },
    "salon": {
        "open": (
            "{greeting}, this is {business}. Sorry we missed your call - we may be with a client! "
            "Reply with the service and day you want and we will confirm.{book}"
        ),
        "closed": (
            "{greeting}, this is {business}. Sorry we missed your call - we reopen {reopens}. "
            "Reply with the service and day you want and we will confirm.{book}"
        ),
        "urgent": GENERIC["open"],
    },
    "real-estate": {
        "open": (
            "{greeting}, this is {business}. Sorry we missed your call! "
            "Are you buying, selling or asking about a listing? Reply and an agent will respond.{book}"
        ),
        "closed": (
            "{greeting}, this is {business}. Sorry we missed your call - we reopen {reopens}. "
            "Reply with the property or what you need and an agent will respond.{book}"
        ),
        "urgent": GENERIC["open"],
    },
}

OPT_OUT = " Reply STOP to opt out."


def get_templates(industry: str) -> Dict[str, str]:
    """Return the open/closed/urgent templates for an industry (falls back to general)."""
    return INDUSTRIES.get(industry.strip().lower(), GENERIC)
