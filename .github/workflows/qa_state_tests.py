#!/usr/bin/env python3
"""
qa_state_tests.py - State transition test generator for manual QA.

Describe how a feature moves between states (an order, a ticket, a user account,
a subscription...) and get ready-to-run test cases:
  - VALID tests that walk the system through every allowed transition
  - INVALID tests for every state/event combination that should be rejected
  - optional 1-switch tests covering every pair of back-to-back transitions
  - a Mermaid diagram you can paste into a GitHub README
No dependencies (Python 3.8+).

Model file format (plain text):
    # comments start with a hash
    initial: Draft
    final: Delivered, Cancelled
    Draft --submit--> Submitted
    Submitted --approve--> Approved
    Submitted --cancel--> Cancelled
    Approved --ship--> Shipped
    Shipped --deliver--> Delivered

Usage examples:
    python qa_state_tests.py demo
    python qa_state_tests.py model.txt
    python qa_state_tests.py model.txt --switch1 --format markdown
    python qa_state_tests.py model.txt --no-negative --format csv --output tests.csv
    python qa_state_tests.py model.txt --diagram
"""

import argparse
import csv
import io
import re
import sys
from collections import deque
from pathlib import Path

DEMO_MODEL = """\
# Order lifecycle
initial: Draft
final: Delivered, Cancelled
Draft --submit--> Submitted
Draft --discard--> Cancelled
Submitted --approve--> Approved
Submitted --reject--> Draft
Submitted --cancel--> Cancelled
Approved --ship--> Shipped
Approved --cancel--> Cancelled
Shipped --deliver--> Delivered
Shipped --return--> Approved
"""

TRANSITION_RE = re.compile(r"^(.+?)\s*--\s*(.+?)\s*-->\s*(.+)$")


# ---------- model ----------
class Model:
    def __init__(self, text):
        self.initial = None
        self.finals = set()
        self.transitions = []  # (from, event, to) in file order
        self.table = {}        # (from, event) -> to
        self._parse(text)
        self.states = self._collect_states()
        self.events = sorted({e for _, e, _ in self.transitions})

    def _parse(self, text):
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith("initial:"):
                self.initial = line.split(":", 1)[1].strip()
            elif low.startswith("final:"):
                self.finals = {s.strip() for s in line.split(":", 1)[1].split(",") if s.strip()}
            else:
                m = TRANSITION_RE.match(line)
                if not m:
                    sys.exit(f"Line {n}: can't parse '{raw.strip()}'. Use: State --event--> State")
                src, ev, dst = (g.strip() for g in m.groups())
                if (src, ev) in self.table:
                    if self.table[(src, ev)] != dst:
                        sys.exit(f"Line {n}: '{src}' + '{ev}' leads to both '{self.table[(src, ev)]}' and '{dst}'. "
                                 "Each state/event pair must have one outcome.")
                    continue  # exact duplicate, ignore
                self.table[(src, ev)] = dst
                self.transitions.append((src, ev, dst))
        if not self.transitions:
            sys.exit("No transitions found.")
        if not self.initial:
            sys.exit("Missing 'initial: <state>' line.")

    def _collect_states(self):
        seen = [self.initial]
        for s, _, d in self.transitions:
            for x in (s, d):
                if x not in seen:
                    seen.append(x)
        return seen

    def outgoing(self, state):
        return [(s, e, d) for s, e, d in self.transitions if s == state]

    def shortest_path(self, start, goal):
        """Shortest list of transitions from start to goal (BFS), or None."""
        if start == goal:
            return []
        seen, queue = {start}, deque([(start, [])])
        while queue:
            state, path = queue.popleft()
            for t in self.outgoing(state):
                if t[2] in seen:
                    continue
                if t[2] == goal:
                    return path + [t]
                seen.add(t[2])
                queue.append((t[2], path + [t]))
        return None

    def reachable(self):
        seen, stack = {self.initial}, [self.initial]
        while stack:
            for _, _, d in self.outgoing(stack.pop()):
                if d not in seen:
                    seen.add(d)
                    stack.append(d)
        return seen

    def health_warnings(self):
        out = []
        reach = self.reachable()
        for s in self.states:
            if s not in reach:
                out.append(f"State '{s}' is unreachable from '{self.initial}'.")
            if not self.outgoing(s) and s not in self.finals:
                out.append(f"State '{s}' is a dead end but isn't listed as final.")
        for f in self.finals:
            if f not in self.states:
                out.append(f"Final state '{f}' doesn't appear in any transition.")
            elif self.outgoing(f):
                out.append(f"Final state '{f}' has outgoing transitions.")
        return out


# ---------- test generation ----------
def valid_tests(model):
    """Paths from the initial state that together cover every reachable transition."""
    reach = model.reachable()
    uncovered = {t for t in model.transitions if t[0] in reach}
    tests = []
    while uncovered:
        state, path = model.initial, []
        progressed = False
        while True:
            # find the closest uncovered transition from where we are
            best = None
            for t in sorted(uncovered, key=lambda x: model.transitions.index(x)):
                leg = model.shortest_path(state, t[0])
                if leg is not None and (best is None or len(leg) < len(best[0])):
                    best = (leg, t)
            if best is None:
                break
            leg, t = best
            path += leg + [t]
            uncovered -= {t}
            state = t[2]
            progressed = True
        if not progressed:
            break
        tests.append(path)
    return tests


def switch1_tests(model, base_paths):
    """Extra paths so every pair of consecutive transitions is exercised."""
    reach = model.reachable()
    wanted = {(a, b) for a in model.transitions for b in model.transitions
              if a[2] == b[0] and a[0] in reach}
    for path in base_paths:
        wanted -= set(zip(path, path[1:]))
    extra = []
    for a, b in sorted(wanted, key=lambda p: (model.transitions.index(p[0]), model.transitions.index(p[1]))):
        leg = model.shortest_path(model.initial, a[0])
        if leg is not None:
            extra.append(leg + [a, b])
    return extra


def invalid_tests(model):
    """For every reachable state and every event not allowed there: expect a rejection."""
    tests = []
    for state in model.states:
        setup = model.shortest_path(model.initial, state)
        if setup is None:
            continue
        for event in model.events:
            if (state, event) not in model.table:
                tests.append((setup, state, event))
    return tests


# ---------- rendering ----------
def describe_path(model, path):
    if not path:
        return f"Start in {model.initial}"
    parts = [f"Start in {model.initial}"]
    parts += [f"do '{e}' -> {d}" for _, e, d in path]
    return "; ".join(parts)


def build_rows(model, args):
    rows = []
    base = valid_tests(model)
    for i, path in enumerate(base, 1):
        rows.append([f"ST-V{i:02d}", "Valid", describe_path(model, path),
                     f"System ends in '{path[-1][2]}' and every step succeeds"])
    if args.switch1:
        for i, path in enumerate(switch1_tests(model, base), 1):
            rows.append([f"ST-S{i:02d}", "1-switch", describe_path(model, path),
                         f"Both back-to-back steps succeed; ends in '{path[-1][2]}'"])
    if not args.no_negative:
        for i, (setup, state, event) in enumerate(invalid_tests(model), 1):
            steps = describe_path(model, setup) + f"; then try '{event}'"
            rows.append([f"ST-I{i:02d}", "Invalid", steps,
                         f"'{event}' is rejected (disabled or error) and state stays '{state}'"])
    return rows


def render(rows, fmt):
    header = ["Test ID", "Type", "Steps", "Expected Result"]
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header + ["Actual Result", "Status"])
        w.writerows([r + ["", ""] for r in rows])
        return buf.getvalue().rstrip("\n")
    if fmt == "markdown":
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(c.replace("|", "/") for c in r) + " |" for r in rows]
        return "\n".join(lines)
    out = []
    for r in rows:
        out.append(f"{r[0]}  [{r[1]}]\n    Steps   : {r[2]}\n    Expected: {r[3]}")
    return "\n\n".join(out)


def mermaid(model):
    lines = ["```mermaid", "stateDiagram-v2", f"    [*] --> {model.initial.replace(' ', '_')}"]
    for s, e, d in model.transitions:
        lines.append(f"    {s.replace(' ', '_')} --> {d.replace(' ', '_')}: {e}")
    for f in sorted(model.finals):
        lines.append(f"    {f.replace(' ', '_')} --> [*]")
    lines.append("```")
    return "\n".join(lines)


# ---------- CLI ----------
def main():
    p = argparse.ArgumentParser(description="State transition test generator")
    p.add_argument("model", help="Path to a model file, or the word: demo")
    p.add_argument("--switch1", action="store_true", help="Also cover every pair of consecutive transitions")
    p.add_argument("--no-negative", action="store_true", help="Skip invalid-transition tests")
    p.add_argument("--format", choices=["text", "markdown", "csv"], default="text")
    p.add_argument("--diagram", action="store_true", help="Print a Mermaid state diagram instead of tests")
    p.add_argument("--output", help="Write to a file instead of printing")
    args = p.parse_args()

    if args.model == "demo":
        text = DEMO_MODEL
    else:
        path = Path(args.model)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        text = path.read_text(encoding="utf-8")

    model = Model(text)
    result = mermaid(model) if args.diagram else render(build_rows(model, args), args.format)

    if args.output:
        Path(args.output).write_text(result + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(result)

    for w in model.health_warnings():
        print(f"Warning: {w}", file=sys.stderr)
    if not args.diagram:
        n = len(build_rows(model, args))
        print(f"\n{len(model.states)} states, {len(model.transitions)} transitions, {n} tests generated.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
