#!/usr/bin/env python3
"""
qa_tracker.py - A tiny command-line tool for manual QA engineers.

Manage test cases, record test runs, log bugs, and generate a summary report.
No dependencies (Python 3.8+). Data is stored in qa_data.json next to the script.

Usage examples:
    python qa_tracker.py add-case "Login with valid user" --module Login --priority High
    python qa_tracker.py list-cases
    python qa_tracker.py run TC-001 pass
    python qa_tracker.py run TC-002 fail --bug "Error message missing" --severity High
    python qa_tracker.py list-bugs
    python qa_tracker.py summary
    python qa_tracker.py export report.md
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

DATA_FILE = Path(__file__).with_name("qa_data.json")
STATUSES = ["not run", "pass", "fail", "blocked"]
PRIORITIES = ["low", "medium", "high", "critical"]
SEVERITIES = ["low", "medium", "high", "critical"]


# ---------- storage ----------
def load():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"cases": [], "bugs": []}


def save(data):
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def next_id(items, prefix):
    return f"{prefix}-{len(items) + 1:03d}"


def find(items, item_id):
    for item in items:
        if item["id"].lower() == item_id.lower():
            return item
    return None


# ---------- commands ----------
def add_case(args, data):
    case = {
        "id": next_id(data["cases"], "TC"),
        "title": args.title,
        "module": args.module,
        "priority": args.priority,
        "steps": args.steps,
        "expected": args.expected,
        "status": "not run",
        "bug_id": None,
        "last_run": None,
    }
    data["cases"].append(case)
    save(data)
    print(f"Added {case['id']}: {case['title']}")


def list_cases(args, data):
    cases = data["cases"]
    if args.status:
        cases = [c for c in cases if c["status"] == args.status]
    if args.module:
        cases = [c for c in cases if c["module"].lower() == args.module.lower()]
    if not cases:
        print("No test cases found.")
        return
    print(f"{'ID':<8}{'Module':<14}{'Priority':<10}{'Status':<10}Title")
    print("-" * 70)
    for c in cases:
        print(f"{c['id']:<8}{c['module'][:12]:<14}{c['priority']:<10}{c['status']:<10}{c['title']}")


def run_case(args, data):
    case = find(data["cases"], args.case_id)
    if not case:
        sys.exit(f"Test case {args.case_id} not found.")
    case["status"] = args.result
    case["last_run"] = str(date.today())

    if args.result == "fail" and args.bug:
        bug = {
            "id": next_id(data["bugs"], "BUG"),
            "title": args.bug,
            "severity": args.severity,
            "status": "open",
            "test_case": case["id"],
            "reported": str(date.today()),
        }
        data["bugs"].append(bug)
        case["bug_id"] = bug["id"]
        print(f"Logged {bug['id']} ({bug['severity']}): {bug['title']}")

    save(data)
    print(f"{case['id']} marked as {args.result.upper()}")


def add_bug(args, data):
    bug = {
        "id": next_id(data["bugs"], "BUG"),
        "title": args.title,
        "severity": args.severity,
        "status": "open",
        "test_case": args.case,
        "reported": str(date.today()),
    }
    data["bugs"].append(bug)
    save(data)
    print(f"Logged {bug['id']}: {bug['title']}")


def list_bugs(args, data):
    bugs = data["bugs"]
    if args.status:
        bugs = [b for b in bugs if b["status"] == args.status]
    if not bugs:
        print("No bugs found.")
        return
    print(f"{'ID':<9}{'Severity':<10}{'Status':<8}{'Case':<8}Title")
    print("-" * 70)
    for b in bugs:
        print(f"{b['id']:<9}{b['severity']:<10}{b['status']:<8}{(b['test_case'] or '-'):<8}{b['title']}")


def close_bug(args, data):
    bug = find(data["bugs"], args.bug_id)
    if not bug:
        sys.exit(f"Bug {args.bug_id} not found.")
    bug["status"] = "closed"
    save(data)
    print(f"{bug['id']} closed.")


def stats(data):
    cases = data["cases"]
    counts = {s: sum(1 for c in cases if c["status"] == s) for s in STATUSES}
    executed = counts["pass"] + counts["fail"]
    pass_rate = (counts["pass"] / executed * 100) if executed else 0.0
    open_bugs = [b for b in data["bugs"] if b["status"] == "open"]
    return counts, executed, pass_rate, open_bugs


def summary(args, data):
    counts, executed, pass_rate, open_bugs = stats(data)
    total = len(data["cases"])
    print("=== Test Summary ===")
    print(f"Total cases : {total}")
    for s in STATUSES:
        print(f"  {s.title():<9}: {counts[s]}")
    print(f"Pass rate   : {pass_rate:.1f}% ({executed} executed)")
    print(f"Open bugs   : {len(open_bugs)}")
    critical = [b for b in open_bugs if b["severity"] == "critical"]
    if critical:
        print(f"WARNING     : {len(critical)} open critical bug(s)")


def export_report(args, data):
    counts, executed, pass_rate, open_bugs = stats(data)
    lines = [
        f"# QA Test Report - {date.today()}",
        "",
        "## Summary",
        f"- Total cases: {len(data['cases'])}",
        *[f"- {s.title()}: {counts[s]}" for s in STATUSES],
        f"- Pass rate: {pass_rate:.1f}%",
        f"- Open bugs: {len(open_bugs)}",
        "",
        "## Test Cases",
        "| ID | Module | Priority | Status | Title |",
        "|----|--------|----------|--------|-------|",
        *[f"| {c['id']} | {c['module']} | {c['priority']} | {c['status']} | {c['title']} |"
          for c in data["cases"]],
        "",
        "## Bugs",
        "| ID | Severity | Status | Test Case | Title |",
        "|----|----------|--------|-----------|-------|",
        *[f"| {b['id']} | {b['severity']} | {b['status']} | {b['test_case'] or '-'} | {b['title']} |"
          for b in data["bugs"]],
    ]
    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {args.output}")


# ---------- CLI ----------
def build_parser():
    p = argparse.ArgumentParser(description="Manual QA test case and bug tracker")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add-case", help="Add a test case")
    a.add_argument("title")
    a.add_argument("--module", default="General")
    a.add_argument("--priority", choices=PRIORITIES, default="medium")
    a.add_argument("--steps", default="")
    a.add_argument("--expected", default="")
    a.set_defaults(func=add_case)

    l = sub.add_parser("list-cases", help="List test cases")
    l.add_argument("--status", choices=STATUSES)
    l.add_argument("--module")
    l.set_defaults(func=list_cases)

    r = sub.add_parser("run", help="Record a test result")
    r.add_argument("case_id")
    r.add_argument("result", choices=["pass", "fail", "blocked"])
    r.add_argument("--bug", help="Bug title to log automatically when failing")
    r.add_argument("--severity", choices=SEVERITIES, default="medium")
    r.set_defaults(func=run_case)

    b = sub.add_parser("add-bug", help="Log a bug manually")
    b.add_argument("title")
    b.add_argument("--severity", choices=SEVERITIES, default="medium")
    b.add_argument("--case", help="Related test case ID")
    b.set_defaults(func=add_bug)

    lb = sub.add_parser("list-bugs", help="List bugs")
    lb.add_argument("--status", choices=["open", "closed"])
    lb.set_defaults(func=list_bugs)

    cb = sub.add_parser("close-bug", help="Close a bug")
    cb.add_argument("bug_id")
    cb.set_defaults(func=close_bug)

    s = sub.add_parser("summary", help="Show execution summary")
    s.set_defaults(func=summary)

    e = sub.add_parser("export", help="Export a Markdown report")
    e.add_argument("output", nargs="?", default="qa_report.md")
    e.set_defaults(func=export_report)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args, load())


if __name__ == "__main__":
    main()
