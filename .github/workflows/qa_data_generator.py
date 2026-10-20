#!/usr/bin/env python3
"""
qa_data_generator.py - Test data generator for manual QA engineers.

Generates fake users plus the edge-case inputs testers use for form,
boundary and negative testing. No dependencies (Python 3.8+).

Usage examples:
    python qa_data_generator.py users --count 5
    python qa_data_generator.py users --count 20 --format csv --output users.csv
    python qa_data_generator.py strings
    python qa_data_generator.py boundary --min 3 --max 20
    python qa_data_generator.py dates
    python qa_data_generator.py cards
    python qa_data_generator.py password --length 16
"""

import argparse
import csv
import io
import json
import random
import string
import sys
from datetime import date, timedelta
from pathlib import Path

FIRST_NAMES = ["Alex", "Maria", "Chen", "Aisha", "Liam", "Sofia", "Omar", "Emma", "Noah", "Yuki"]
LAST_NAMES = ["Smith", "Garcia", "Nguyen", "Khan", "O'Brien", "Müller", "Silva", "Kim", "Brown", "Lopez"]
DOMAINS = ["example.com", "test.org", "mailinator.test"]
ZIP_CODES = ["90210", "10001", "60601", "73301", "02108"]

# Common QA edge-case inputs for text fields (safe, harmless test strings)
SPECIAL_STRINGS = {
    "empty": "",
    "single space": " ",
    "leading/trailing spaces": "  padded  ",
    "very long (300 chars)": "A" * 300,
    "numbers only": "1234567890",
    "special characters": "!@#$%^&*()_+-=[]{}|;':\",./<>?",
    "unicode / accents": "Zoë Müller-Łukasz",
    "emoji": "Test 😀🎉",
    "right-to-left text": "مرحبا بالعالم",
    "chinese characters": "测试用户",
    "HTML tags": "<b>bold</b>",
    "script tag (XSS check)": "<script>alert('xss')</script>",
    "SQL quote (injection check)": "' OR '1'='1",
    "newline inside text": "line1\nline2",
    "tab character": "col1\tcol2",
    "null-like words": "null",
    "undefined-like words": "undefined",
    "negative number": "-1",
    "decimal number": "3.14159",
    "zero": "0",
}

# Public test card numbers published by payment providers (never real cards)
TEST_CARDS = [
    ("Visa (valid test)", "4242424242424242"),
    ("Mastercard (valid test)", "5555555555554444"),
    ("Amex (valid test)", "378282246310005"),
    ("Card declined (Stripe test)", "4000000000000002"),
    ("Invalid: fails Luhn check", "4242424242424241"),
    ("Invalid: too short", "42424242"),
    ("Invalid: letters", "abcdabcdabcdabcd"),
]


def make_user(rng):
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    handle = f"{first}.{last}".lower().replace("'", "").replace("ü", "u")
    return {
        "first_name": first,
        "last_name": last,
        "email": f"{handle}{rng.randint(1, 999)}@{rng.choice(DOMAINS)}",
        "phone": f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
        "zip": rng.choice(ZIP_CODES),
        "birthdate": str(date(1950, 1, 1) + timedelta(days=rng.randint(0, 20000))),
    }


def gen_password(length, rng):
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!@#$%^&*"]
    chars = [rng.choice(p) for p in pools]  # guarantee one from each pool
    allchars = "".join(pools)
    chars += [rng.choice(allchars) for _ in range(max(0, length - len(chars)))]
    rng.shuffle(chars)
    return "".join(chars)


def to_csv(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def output(text, path):
    if path:
        Path(path).write_text(text, encoding="utf-8")
        print(f"Written to {path}")
    else:
        print(text)


# ---------- commands ----------
def cmd_users(args, rng):
    users = [make_user(rng) for _ in range(args.count)]
    if args.format == "json":
        text = json.dumps(users, indent=2, ensure_ascii=False)
    elif args.format == "csv":
        text = to_csv(users)
    else:
        text = "\n".join(f"{u['first_name']} {u['last_name']} | {u['email']} | {u['phone']} | {u['zip']} | {u['birthdate']}" for u in users)
    output(text, args.output)


def cmd_strings(args, rng):
    rows = [{"case": k, "value": v if len(v) <= 40 else v[:37] + "..."} for k, v in SPECIAL_STRINGS.items()]
    if args.format == "json":
        text = json.dumps(SPECIAL_STRINGS, indent=2, ensure_ascii=False)
    elif args.format == "csv":
        text = to_csv([{"case": k, "value": v} for k, v in SPECIAL_STRINGS.items()])
    else:
        text = "\n".join(f"{r['case']:<30}{r['value']!r}" for r in rows)
    output(text, args.output)


def cmd_boundary(args, rng):
    """Boundary value analysis for a text field with min/max length."""
    lo, hi = args.min, args.max
    if lo > hi:
        sys.exit("--min must be less than or equal to --max")
    cases = [
        (f"below min ({lo - 1} chars)", lo - 1, "should be REJECTED"),
        (f"at min ({lo} chars)", lo, "should be ACCEPTED"),
        (f"just above min ({lo + 1} chars)", lo + 1, "should be ACCEPTED"),
        (f"nominal ({(lo + hi) // 2} chars)", (lo + hi) // 2, "should be ACCEPTED"),
        (f"just below max ({hi - 1} chars)", hi - 1, "should be ACCEPTED"),
        (f"at max ({hi} chars)", hi, "should be ACCEPTED"),
        (f"above max ({hi + 1} chars)", hi + 1, "should be REJECTED"),
    ]
    lines = [f"Boundary values for length {lo}-{hi}", "-" * 60]
    for label, n, verdict in cases:
        if n < 0:
            continue
        sample = ("x" * n) if n <= 30 else ("x" * 27 + "...")
        lines.append(f"{label:<34}{verdict:<20}'{sample}'")
    output("\n".join(lines), args.output)


def cmd_dates(args, rng):
    today = date.today()
    rows = [
        ("Today", today),
        ("Yesterday", today - timedelta(days=1)),
        ("Tomorrow", today + timedelta(days=1)),
        ("One year ago", today.replace(year=today.year - 1, day=min(today.day, 28))),
        ("Leap day (valid)", date(2024, 2, 29)),
        ("End of year", date(today.year, 12, 31)),
        ("Start of year", date(today.year, 1, 1)),
        ("Far past", date(1900, 1, 1)),
        ("Far future", date(2099, 12, 31)),
        ("Under 18 years old", today - timedelta(days=365 * 17)),
        ("Over 65 years old", today - timedelta(days=365 * 66)),
    ]
    invalid = [
        ("INVALID: Feb 30", "2025-02-30"),
        ("INVALID: month 13", "2025-13-01"),
        ("INVALID: leap day in non-leap year", "2023-02-29"),
        ("INVALID: wrong format", "31/31/2025"),
        ("INVALID: text", "not a date"),
    ]
    lines = [f"{label:<36}{d.isoformat()}  ({d.strftime('%m/%d/%Y')})" for label, d in rows]
    lines += [f"{label:<36}{val}" for label, val in invalid]
    output("\n".join(lines), args.output)


def cmd_cards(args, rng):
    lines = [f"{label:<32}{number}" for label, number in TEST_CARDS]
    lines.append("")
    lines.append("Use any future expiry date and any 3-digit CVC (4 for Amex).")
    output("\n".join(lines), args.output)


def cmd_password(args, rng):
    if args.length < 4:
        sys.exit("--length must be at least 4")
    pwds = [gen_password(args.length, rng) for _ in range(args.count)]
    output("\n".join(pwds), args.output)


# ---------- CLI ----------
def build_parser():
    p = argparse.ArgumentParser(description="Test data generator for manual QA")
    p.add_argument("--seed", type=int, help="Seed for reproducible output")
    sub = p.add_subparsers(dest="command", required=True)

    def add_output(sp):
        sp.add_argument("--output", help="Write to file instead of printing")

    u = sub.add_parser("users", help="Generate fake users")
    u.add_argument("--count", type=int, default=5)
    u.add_argument("--format", choices=["text", "json", "csv"], default="text")
    add_output(u); u.set_defaults(func=cmd_users)

    s = sub.add_parser("strings", help="Edge-case strings for text field testing")
    s.add_argument("--format", choices=["text", "json", "csv"], default="text")
    add_output(s); s.set_defaults(func=cmd_strings)

    b = sub.add_parser("boundary", help="Boundary values for a field length")
    b.add_argument("--min", type=int, required=True)
    b.add_argument("--max", type=int, required=True)
    add_output(b); b.set_defaults(func=cmd_boundary)

    d = sub.add_parser("dates", help="Valid and invalid date test inputs")
    add_output(d); d.set_defaults(func=cmd_dates)

    c = sub.add_parser("cards", help="Public payment test card numbers")
    add_output(c); c.set_defaults(func=cmd_cards)

    pw = sub.add_parser("password", help="Random passwords")
    pw.add_argument("--length", type=int, default=12)
    pw.add_argument("--count", type=int, default=3)
    add_output(pw); pw.set_defaults(func=cmd_password)

    return p


def main():
    args = build_parser().parse_args()
    rng = random.Random(args.seed)
    args.func(args, rng)


if __name__ == "__main__":
    main()
