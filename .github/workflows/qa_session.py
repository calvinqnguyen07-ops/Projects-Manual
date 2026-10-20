#!/usr/bin/env python3
"""
qa_session.py - Exploratory testing session logger for manual QA engineers.

Based on session-based test management: set a charter and a time box, take
tagged notes while you test, track how your time is split, and get a Markdown
report when you finish. No dependencies (Python 3.8+).

Usage:
    python qa_session.py                       # start a session (prompts for details)
    python qa_session.py --minutes 45 --tester "Sam" --charter "Explore checkout with invalid input"

While testing, type a note and press Enter. Prefix it with a tag:
    b: cart badge shows 0 after adding item      -> BUG
    i: page feels slow on login                  -> ISSUE
    q: should the tax apply to shipping?         -> QUESTION
    d: try a coupon with unicode characters      -> IDEA
    (no prefix)                                  -> NOTE

Commands:
    /mode setup|test|bug    switch what you're currently doing (tracks time split)
    /time                   show elapsed and remaining time
    /notes                  show all notes so far
    /done                   finish and save the report
    /help                   show this help
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

TAGS = {"b": "BUG", "i": "ISSUE", "q": "QUESTION", "d": "IDEA"}
MODES = ["setup", "test", "bug"]
OUTPUT_DIR = Path("qa_sessions")


def fmt(seconds):
    seconds = int(max(0, seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Session:
    def __init__(self, charter, tester, minutes):
        self.charter = charter
        self.tester = tester
        self.minutes = minutes
        self.started = datetime.now()
        self.start_clock = time.monotonic()
        self.notes = []
        self.mode = "test"
        self.mode_since = self.start_clock
        self.mode_time = {m: 0.0 for m in MODES}
        self.warned = False

    def elapsed(self):
        return time.monotonic() - self.start_clock

    def remaining(self):
        return self.minutes * 60 - self.elapsed()

    def set_mode(self, mode):
        now = time.monotonic()
        self.mode_time[self.mode] += now - self.mode_since
        self.mode, self.mode_since = mode, now

    def add_note(self, text):
        tag = "NOTE"
        if len(text) > 2 and text[1] == ":" and text[0].lower() in TAGS:
            tag, text = TAGS[text[0].lower()], text[2:].strip()
        self.notes.append({"time": fmt(self.elapsed()), "tag": tag, "text": text})
        return tag

    def finish(self):
        self.set_mode(self.mode)  # flush time for the current mode
        self.ended = datetime.now()

    def counts(self):
        out = {}
        for n in self.notes:
            out[n["tag"]] = out.get(n["tag"], 0) + 1
        return out

    def to_markdown(self):
        total = sum(self.mode_time.values()) or 1
        lines = [
            "# Exploratory Testing Session Report",
            "",
            f"- **Charter:** {self.charter}",
            f"- **Tester:** {self.tester}",
            f"- **Started:** {self.started:%Y-%m-%d %H:%M}",
            f"- **Time box:** {self.minutes} min (actual: {fmt(total)})",
            "",
            "## Time breakdown",
            *[f"- {m.title()}: {fmt(t)} ({t / total * 100:.0f}%)" for m, t in self.mode_time.items()],
            "",
            "## Summary",
            *[f"- {tag}: {n}" for tag, n in sorted(self.counts().items())],
        ]
        for tag in ["BUG", "ISSUE", "QUESTION", "IDEA", "NOTE"]:
            items = [n for n in self.notes if n["tag"] == tag]
            if items:
                lines += ["", f"## {tag.title()}s"]
                lines += [f"- [{n['time']}] {n['text']}" for n in items]
        lines += ["", "## Full timeline", "| Time | Type | Note |", "|------|------|------|"]
        lines += [f"| {n['time']} | {n['tag']} | {n['text'].replace('|', '/')} |" for n in self.notes]
        return "\n".join(lines) + "\n"

    def to_dict(self):
        return {
            "charter": self.charter, "tester": self.tester, "minutes": self.minutes,
            "started": self.started.isoformat(), "time_by_mode": self.mode_time,
            "notes": self.notes,
        }


def ask(prompt, default=None):
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def save(session):
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = session.started.strftime("%Y%m%d_%H%M")
    md = OUTPUT_DIR / f"session_{stamp}.md"
    js = OUTPUT_DIR / f"session_{stamp}.json"
    md.write_text(session.to_markdown(), encoding="utf-8")
    js.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    return md, js


def main():
    p = argparse.ArgumentParser(description="Exploratory testing session logger")
    p.add_argument("--charter")
    p.add_argument("--tester")
    p.add_argument("--minutes", type=int)
    args = p.parse_args()

    print("=== Exploratory Testing Session ===")
    charter = args.charter or ask("Charter (what are you exploring?)", "General exploration")
    tester = args.tester or ask("Tester name", "Tester")
    minutes = args.minutes or int(ask("Time box in minutes", "30"))

    s = Session(charter, tester, minutes)
    print(f"\nSession started. {minutes} min time box. Type /help for commands.\n")

    try:
        while True:
            try:
                line = input(f"[{fmt(s.elapsed())}|{s.mode}] > ").strip()
            except EOFError:
                break
            if not line:
                continue

            if s.remaining() <= 0 and not s.warned:
                print("*** TIME BOX REACHED. Wrap up or type /done. ***")
                s.warned = True

            if line == "/done":
                break
            elif line == "/help":
                print(__doc__)
            elif line == "/time":
                print(f"Elapsed {fmt(s.elapsed())} | Remaining {fmt(s.remaining())}")
            elif line == "/notes":
                for n in s.notes:
                    print(f"  [{n['time']}] {n['tag']:<8} {n['text']}")
            elif line.startswith("/mode"):
                parts = line.split()
                if len(parts) == 2 and parts[1] in MODES:
                    s.set_mode(parts[1])
                    print(f"Mode: {s.mode}")
                else:
                    print("Usage: /mode setup|test|bug")
            elif line.startswith("/"):
                print("Unknown command. Type /help.")
            else:
                print(f"  logged as {s.add_note(line)}")
    except KeyboardInterrupt:
        print("\nInterrupted. Saving session...")

    s.finish()
    md, js = save(s)
    print(f"\nSession finished. {len(s.notes)} notes, {s.counts().get('BUG', 0)} bug(s).")
    print(f"Report: {md}\nData:   {js}")


if __name__ == "__main__":
    main()
