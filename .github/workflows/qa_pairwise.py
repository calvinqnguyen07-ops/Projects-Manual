#!/usr/bin/env python3
"""
qa_pairwise.py - Pairwise (all-pairs) test case generator for manual QA.

Testing every combination of browsers, operating systems, user roles, etc. gets
huge fast. Pairwise testing covers every pair of values at least once with far
fewer test cases. No dependencies (Python 3.8+).

Usage examples:
    python qa_pairwise.py demo
    python qa_pairwise.py "Browser=Chrome,Firefox,Safari" "OS=Windows,macOS,Linux" "Role=Admin,User,Guest"
    python qa_pairwise.py "Browser=Chrome,Safari" "OS=Windows,macOS" --exclude "Browser=Safari&OS=Windows"
    python qa_pairwise.py --file params.json --format csv --output matrix.csv
    python qa_pairwise.py "A=1,2,3" "B=x,y" --format markdown --with-results

params.json looks like:
    {"Browser": ["Chrome", "Firefox"], "OS": ["Windows", "macOS"], "Language": ["EN", "ES"]}

Exclusions: --exclude "Param1=value&Param2=value" marks a combination that is
impossible (e.g. Safari on Windows). It will never appear in a generated test.
"""

import argparse
import csv
import io
import itertools
import json
import random
import sys
from pathlib import Path

DEMO = {
    "Browser": ["Chrome", "Firefox", "Safari", "Edge"],
    "OS": ["Windows", "macOS", "Linux"],
    "User role": ["Admin", "Customer", "Guest"],
    "Payment": ["Card", "PayPal", "Gift card"],
}
DEMO_EXCLUDES = [{"Browser": "Safari", "OS": "Windows"}, {"Browser": "Safari", "OS": "Linux"}]


# ---------- input parsing ----------
def parse_param(text):
    if "=" not in text:
        sys.exit(f"Bad parameter '{text}'. Use Name=value1,value2,...")
    name, values = text.split("=", 1)
    vals = [v.strip() for v in values.split(",") if v.strip()]
    if not name.strip() or len(vals) < 2:
        sys.exit(f"Parameter '{text}' needs a name and at least two values.")
    if len(set(vals)) != len(vals):
        sys.exit(f"Parameter '{name}' has duplicate values.")
    return name.strip(), vals


def parse_exclusion(text, params):
    parts = {}
    for chunk in text.split("&"):
        if "=" not in chunk:
            sys.exit(f"Bad exclusion '{text}'. Use Param=value&Param=value")
        k, v = (s.strip() for s in chunk.split("=", 1))
        if k not in params:
            sys.exit(f"Exclusion refers to unknown parameter '{k}'.")
        if v not in params[k]:
            sys.exit(f"Exclusion refers to unknown value '{v}' for '{k}'.")
        parts[k] = v
    if len(parts) < 2:
        sys.exit(f"Exclusion '{text}' needs at least two parameters.")
    return parts


# ---------- core algorithm ----------
def is_excluded(assignment, exclusions):
    """assignment: dict of param -> value (may be partial)."""
    return any(all(assignment.get(k) == v for k, v in ex.items()) for ex in exclusions)


def all_pairs(names, params, exclusions):
    pairs = set()
    for a, b in itertools.combinations(names, 2):
        for va in params[a]:
            for vb in params[b]:
                if not is_excluded({a: va, b: vb}, exclusions):
                    pairs.add(((a, va), (b, vb)))
    return pairs


def test_pairs(test, names):
    return {((a, test[a]), (b, test[b])) for a, b in itertools.combinations(names, 2)}


def build_candidate(seed_pair, names, params, exclusions, uncovered, rng):
    (pa, va), (pb, vb) = seed_pair
    test = {pa: va, pb: vb}
    remaining = [n for n in names if n not in test]
    rng.shuffle(remaining)
    for name in remaining:
        best, best_score = None, -1
        values = params[name][:]
        rng.shuffle(values)
        for val in values:
            trial = dict(test, **{name: val})
            if is_excluded(trial, exclusions):
                continue
            score = sum(
                1 for other, ov in test.items()
                if tuple(sorted(((name, val), (other, ov)), key=lambda p: names.index(p[0]))) in uncovered
            )
            if score > best_score:
                best, best_score = val, score
        if best is None:
            return None  # dead end because of exclusions
        test[name] = best
    return test


def generate(params, exclusions, seed=None, tries=40):
    names = list(params)
    rng = random.Random(seed)
    uncovered = all_pairs(names, params, exclusions)
    tests, uncoverable = [], []

    while uncovered:
        seed_pair = rng.choice(sorted(uncovered))
        best, best_gain = None, 0
        for _ in range(tries):
            cand = build_candidate(seed_pair, names, params, exclusions, uncovered, rng)
            if cand is None:
                continue
            gain = len(test_pairs(cand, names) & uncovered)
            if gain > best_gain:
                best, best_gain = cand, gain
        if best is None:
            uncoverable.append(seed_pair)
            uncovered.discard(seed_pair)
            continue
        tests.append(best)
        uncovered -= test_pairs(best, names)

    tests.sort(key=lambda t: [params[n].index(t[n]) for n in names])
    return tests, uncoverable


def verify(tests, params, exclusions, uncoverable):
    names = list(params)
    needed = all_pairs(names, params, exclusions) - set(uncoverable)
    covered = set()
    for t in tests:
        if is_excluded(t, exclusions):
            return False
        covered |= test_pairs(t, names)
    return needed <= covered


def full_count(params, exclusions):
    total = 1
    for v in params.values():
        total *= len(v)
    if total > 2_000_000 or not exclusions:
        return total
    names = list(params)
    return sum(1 for combo in itertools.product(*params.values())
               if not is_excluded(dict(zip(names, combo)), exclusions))


# ---------- output ----------
def render(tests, params, fmt, with_results):
    names = list(params)
    header = ["TC"] + names + (["Expected Result", "Actual Result", "Status"] if with_results else [])
    rows = []
    for i, t in enumerate(tests, 1):
        rows.append([f"PW-{i:02d}"] + [t[n] for n in names] + ([""] * 3 if with_results else []))

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
        return buf.getvalue().rstrip("\n")
    if fmt == "markdown":
        lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(lines)
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    fmt_row = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip()
    return "\n".join([fmt_row(header), "  ".join("-" * w for w in widths), *map(fmt_row, rows)])


# ---------- CLI ----------
def main():
    p = argparse.ArgumentParser(description="Pairwise test case generator")
    p.add_argument("params", nargs="*", help='Parameters like "Browser=Chrome,Firefox" or the word: demo')
    p.add_argument("--file", help="JSON file of parameters")
    p.add_argument("--exclude", action="append", default=[], help='Impossible combo, e.g. "Browser=Safari&OS=Windows"')
    p.add_argument("--format", choices=["table", "csv", "markdown"], default="table")
    p.add_argument("--with-results", action="store_true", help="Add Expected/Actual/Status columns")
    p.add_argument("--seed", type=int, default=1, help="Seed for repeatable output (default 1)")
    p.add_argument("--output", help="Write to a file instead of printing")
    args = p.parse_args()

    exclusions = []
    if args.params == ["demo"]:
        params, exclusions = DEMO, DEMO_EXCLUDES
    elif args.file:
        try:
            params = json.loads(Path(args.file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"Could not read {args.file}: {e}")
        if not isinstance(params, dict) or any(not isinstance(v, list) or len(v) < 2 for v in params.values()):
            sys.exit("JSON must be an object where each parameter has a list of at least 2 values.")
        params = {k: [str(x) for x in v] for k, v in params.items()}
    else:
        if not args.params:
            p.print_help()
            sys.exit(1)
        params = dict(parse_param(x) for x in args.params)

    if len(params) < 2:
        sys.exit("Need at least two parameters.")
    exclusions += [parse_exclusion(e, params) for e in args.exclude]

    tests, uncoverable = generate(params, exclusions, seed=args.seed)
    ok = verify(tests, params, exclusions, uncoverable)
    full = full_count(params, exclusions)

    text = render(tests, params, args.format, args.with_results)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(text)

    saved = 100 - len(tests) / full * 100 if full else 0
    print(f"\nFull combinations: {full} | Pairwise tests: {len(tests)} | Reduction: {saved:.0f}%", file=sys.stderr)
    print(f"All valid pairs covered: {'YES' if ok else 'NO'}", file=sys.stderr)
    if uncoverable:
        print(f"Warning: {len(uncoverable)} pair(s) cannot be covered because of your exclusions.", file=sys.stderr)


if __name__ == "__main__":
    main()
