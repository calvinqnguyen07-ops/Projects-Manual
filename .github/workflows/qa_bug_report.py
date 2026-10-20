#!/usr/bin/env python3
"""
qa_bug_report.py - Bug report builder and quality checker for manual QA.

Walks you through writing a well-structured bug report, warns you about common
quality problems (vague title, missing steps, speculation, no evidence), and
saves it as Markdown. You can also lint any existing report in the same format.
No dependencies (Python 3.8+).

Usage:
    python qa_bug_report.py new                    # build a report interactively
    python qa_bug_report.py lint bug_reports/x.md  # check an existing report
    python qa_bug_report.py demo                   # show a good and a bad example
"""

import argparse
import platform
import re
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("bug_reports")
SEVERITIES = ["critical", "high", "medium", "low"]
PRIORITIES = ["P1", "P2", "P3", "P4"]
FREQUENCIES = ["always", "often", "sometimes", "once"]

VAGUE_WORDS = {"broken", "bug", "issue", "problem", "error", "fail", "failed", "fails",
               "wrong", "bad", "weird", "strange", "crash", "crashes", "stuff", "thing"}
VAGUE_PHRASES = ["doesn't work", "does not work", "not working", "isn't working", "is broken"]
SPECULATION = ["maybe", "i think", "probably", "i guess", "perhaps", "might be", "not sure", "seems like"]


# ---------- building and parsing ----------
def to_markdown(r):
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(r["steps"], 1)) or "_none_"
    return f"""# Bug: {r['title']}

- **Module:** {r['module']}
- **Severity:** {r['severity']}
- **Priority:** {r['priority']}
- **Frequency:** {r['frequency']}
- **Environment:** {r['environment']}
- **Reported:** {r['reported']}

## Preconditions
{r['preconditions'] or '_none_'}

## Steps to Reproduce
{steps}

## Expected Result
{r['expected'] or '_none_'}

## Actual Result
{r['actual'] or '_none_'}

## Attachments
{r['attachments'] or '_none_'}

## Notes
{r['notes'] or '_none_'}
"""


def parse_markdown(text):
    r = {k: "" for k in ["title", "module", "severity", "priority", "frequency", "environment",
                         "preconditions", "expected", "actual", "attachments", "notes"]}
    r["steps"] = []
    m = re.search(r"^# Bug:\s*(.+)$", text, re.M)
    r["title"] = m.group(1).strip() if m else ""
    for key, val in re.findall(r"^- \*\*(.+?):\*\*\s*(.*)$", text, re.M):
        r[key.strip().lower()] = val.strip()
    sections = {}
    for name, body in re.findall(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        sections[name.strip().lower()] = body.strip()
    clean = lambda s: "" if s in ("", "_none_") else s
    r["preconditions"] = clean(sections.get("preconditions", ""))
    r["expected"] = clean(sections.get("expected result", ""))
    r["actual"] = clean(sections.get("actual result", ""))
    r["attachments"] = clean(sections.get("attachments", ""))
    r["notes"] = clean(sections.get("notes", ""))
    steps = clean(sections.get("steps to reproduce", ""))
    r["steps"] = [re.sub(r"^\d+\.\s*", "", s).strip() for s in steps.splitlines() if s.strip()]
    return r


# ---------- quality checks ----------
def lint(r):
    """Returns a list of (level, message). Level is ERROR or WARN."""
    out = []
    title = r["title"].strip()
    words = re.findall(r"[A-Za-z']+", title.lower())

    if not title:
        out.append(("ERROR", "Title is missing."))
    else:
        if len(words) < 4:
            out.append(("WARN", "Title is very short. Say what broke and where, e.g. 'Cart badge shows 0 after adding item'."))
        if words and all(w in VAGUE_WORDS or len(w) <= 3 for w in words):
            out.append(("ERROR", "Title is too vague. Describe the specific symptom."))
        if any(p in title.lower() for p in VAGUE_PHRASES):
            out.append(("WARN", "Title says 'doesn't work' without saying what actually happens."))
        if len(title) > 100:
            out.append(("WARN", "Title is over 100 characters. Move details into the description."))

    if not r["steps"]:
        out.append(("ERROR", "No steps to reproduce."))
    elif len(r["steps"]) < 2:
        out.append(("WARN", "Only one step. Include how to get to the starting point."))

    if not r["expected"]:
        out.append(("ERROR", "Expected result is missing."))
    if not r["actual"]:
        out.append(("ERROR", "Actual result is missing."))
    if r["expected"] and r["expected"].strip().lower() == r["actual"].strip().lower():
        out.append(("ERROR", "Expected and actual results are identical, so this isn't a defect as written."))

    if not r["environment"]:
        out.append(("ERROR", "Environment (OS, browser, build) is missing."))
    elif not re.search(r"\d", r["environment"]):
        out.append(("WARN", "Environment has no version numbers (browser version, build, OS version)."))

    if not r["attachments"]:
        out.append(("WARN", "No attachments. Add a screenshot, video or log if possible."))

    body = " ".join([*r["steps"], r["actual"], r["expected"]]).lower()
    found = [w for w in SPECULATION if w in body]
    if found:
        out.append(("WARN", f"Speculative wording found ({', '.join(found)}). Stick to what you observed."))

    if r["severity"].lower() == "critical" and r["frequency"].lower() == "once":
        out.append(("WARN", "Critical but seen only once. Try to reproduce again and note the exact conditions."))
    if r["severity"].lower() not in SEVERITIES:
        out.append(("ERROR", f"Severity must be one of: {', '.join(SEVERITIES)}."))
    return out


def report_lint(r):
    issues = lint(r)
    errors = sum(1 for lvl, _ in issues if lvl == "ERROR")
    warns = len(issues) - errors
    score = max(0, 100 - errors * 20 - warns * 7)
    print(f"\nQuality check: {score}/100 ({errors} error(s), {warns} warning(s))")
    for level, msg in issues:
        print(f"  [{level}] {msg}")
    if not issues:
        print("  Looks great. Ready to submit.")
    return errors


# ---------- interactive ----------
def ask(prompt, default=""):
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def ask_choice(prompt, choices, default):
    while True:
        value = ask(f"{prompt} ({'/'.join(choices)})", default)
        if value.lower() in [c.lower() for c in choices]:
            return next(c for c in choices if c.lower() == value.lower())
        print(f"  Please choose one of: {', '.join(choices)}")


def ask_steps():
    print("Steps to reproduce (one per line, blank line to finish):")
    steps = []
    while True:
        try:
            line = input(f"  {len(steps) + 1}. ").strip()
        except EOFError:
            break
        if not line:
            break
        steps.append(line)
    return steps


def cmd_new(args):
    print("=== New Bug Report ===")
    r = {
        "title": ask("Title"),
        "module": ask("Module / feature", "General"),
        "severity": ask_choice("Severity", SEVERITIES, "medium"),
        "priority": ask_choice("Priority", PRIORITIES, "P3"),
        "frequency": ask_choice("Frequency", FREQUENCIES, "always"),
        "environment": ask("Environment (browser/app version, device)", f"{platform.system()} {platform.release()}"),
        "reported": datetime.now().strftime("%Y-%m-%d"),
        "preconditions": ask("Preconditions (optional)"),
    }
    r["steps"] = ask_steps()
    r["expected"] = ask("Expected result")
    r["actual"] = ask("Actual result")
    r["attachments"] = ask("Attachments (file names or links, optional)")
    r["notes"] = ask("Notes (optional)")

    errors = report_lint(r)
    OUTPUT_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", r["title"].lower()).strip("-")[:40] or "untitled"
    path = OUTPUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}.md"
    path.write_text(to_markdown(r), encoding="utf-8")
    print(f"\nSaved to {path}")
    if errors:
        print("Fix the errors above before submitting (edit the file, then run: lint <file>).")


def cmd_lint(args):
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"File not found: {path}")
    errors = report_lint(parse_markdown(path.read_text(encoding="utf-8")))
    sys.exit(1 if errors else 0)


def cmd_demo(args):
    good = {"title": "Cart badge shows 0 after adding two items as problem_user", "module": "Cart",
            "severity": "high", "priority": "P2", "frequency": "always",
            "environment": "Chrome 130 / Windows 11 / saucedemo.com", "reported": "2026-01-15",
            "preconditions": "Logged in as problem_user with an empty cart",
            "steps": ["Open the inventory page", "Click 'Add to cart' on Sauce Labs Backpack",
                      "Click 'Add to cart' on Sauce Labs Bike Light", "Look at the cart icon"],
            "expected": "Cart badge shows 2", "actual": "Cart badge is empty; items appear in the cart page",
            "attachments": "badge_bug.png", "notes": ""}
    bad = {"title": "Cart broken", "module": "Cart", "severity": "critical", "priority": "P1",
           "frequency": "once", "environment": "my laptop", "reported": "2026-01-15",
           "preconditions": "", "steps": ["Add stuff to cart"], "expected": "It works",
           "actual": "I think the cart is probably broken, maybe a caching problem", "attachments": "", "notes": ""}
    print("######## GOOD EXAMPLE ########")
    print(to_markdown(good))
    report_lint(good)
    print("\n######## BAD EXAMPLE ########")
    print(to_markdown(bad))
    report_lint(bad)


def main():
    p = argparse.ArgumentParser(description="Bug report builder and quality checker")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("new", help="Build a bug report interactively").set_defaults(func=cmd_new)
    l = sub.add_parser("lint", help="Check an existing report")
    l.add_argument("file")
    l.set_defaults(func=cmd_lint)
    sub.add_parser("demo", help="Show a good and a bad example").set_defaults(func=cmd_demo)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
