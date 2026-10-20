#!/usr/bin/env python3
"""
qa_decision_table.py - Decision table test generator for manual QA.

Business rules like "members get free shipping over $100, coupons stack with
discounts..." are where bugs hide. Write the rules once and this tool will:
  - generate one test case per rule
  - find GAPS (condition combinations no rule covers)
  - find CONFLICTS (combinations where two rules disagree)
  - find REDUNDANT rules
  - show the full truth table, or collapse it into the smallest set of rules
No dependencies (Python 3.8+).

Rules file format (plain text):
    # comments start with a hash
    conditions: Member, Order over $100, Has coupon
    actions: Free shipping, 10% discount, Coupon applied

    # one rule per line: Y / N / - (don't care), then ':' then the actions
    Y Y Y : Free shipping, 10% discount, Coupon applied
    Y Y N : Free shipping, 10% discount
    N Y - : Free shipping
    N N N : none

Usage examples:
    python qa_decision_table.py demo
    python qa_decision_table.py rules.txt
    python qa_decision_table.py rules.txt --full-table
    python qa_decision_table.py rules.txt --collapse
    python qa_decision_table.py rules.txt --expand-dc --format csv --output tests.csv
    python qa_decision_table.py rules.txt --include-gaps --format markdown
"""

import argparse
import csv
import io
import itertools
import sys
from pathlib import Path

MAX_CONDITIONS = 12

DEMO = """\
# Shipping and discount rules
conditions: Member, Order over $100, Has coupon
actions: Free shipping, 10% discount, Coupon applied

Y Y Y : Free shipping, 10% discount, Coupon applied
Y Y N : Free shipping, 10% discount
Y N Y : 10% discount, Coupon applied
Y N N : 10% discount
N Y - : Free shipping
N N Y : Coupon applied
# note: N N N (not a member, small order, no coupon) is deliberately missing
"""

YES, NO, ANY = "Y", "N", "-"
TRUE_WORDS = {"y", "yes", "t", "true", "1"}
FALSE_WORDS = {"n", "no", "f", "false", "0"}
ANY_WORDS = {"-", "*", "any", "x"}


# ---------- parsing ----------
class Table:
    def __init__(self, text):
        self.conditions, self.actions, self.rules = [], [], []
        self._parse(text)

    def _parse(self, text):
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith("conditions:"):
                self.conditions = [c.strip() for c in line.split(":", 1)[1].split(",") if c.strip()]
            elif low.startswith("actions:"):
                self.actions = [a.strip() for a in line.split(":", 1)[1].split(",") if a.strip()]
            else:
                if ":" not in line:
                    sys.exit(f"Line {n}: can't parse '{raw.strip()}'. Use: Y N - : action1, action2")
                left, right = line.split(":", 1)
                if not self.conditions or not self.actions:
                    sys.exit(f"Line {n}: define 'conditions:' and 'actions:' before any rules.")
                vals = []
                for tok in left.split():
                    t = tok.lower()
                    vals.append(YES if t in TRUE_WORDS else NO if t in FALSE_WORDS else ANY if t in ANY_WORDS else None)
                if None in vals or len(vals) != len(self.conditions):
                    sys.exit(f"Line {n}: expected {len(self.conditions)} values of Y/N/- before ':' (got '{left.strip()}').")
                acts = frozenset()
                if right.strip().lower() not in ("none", ""):
                    lookup = {a.lower(): a for a in self.actions}
                    chosen = []
                    for a in right.split(","):
                        key = a.strip().lower()
                        if key not in lookup:
                            sys.exit(f"Line {n}: unknown action '{a.strip()}'. Known: {', '.join(self.actions)}")
                        chosen.append(lookup[key])
                    acts = frozenset(chosen)
                self.rules.append((tuple(vals), acts))
        if not self.conditions or not self.actions:
            sys.exit("File needs both 'conditions:' and 'actions:' lines.")
        if len(self.conditions) > MAX_CONDITIONS:
            sys.exit(f"Too many conditions ({len(self.conditions)}). Maximum is {MAX_CONDITIONS}.")
        if not self.rules:
            sys.exit("No rules found.")

    def ordered(self, acts):
        return [a for a in self.actions if a in acts]


# ---------- analysis ----------
def expand(vals):
    pools = [[YES, NO] if v == ANY else [v] for v in vals]
    return list(itertools.product(*pools))


def evaluate(table):
    """Map every combination to ('ok', actions, rule_numbers) / ('conflict', ...) / ('gap',)."""
    cover = {}
    for i, (vals, acts) in enumerate(table.rules, 1):
        for combo in expand(vals):
            cover.setdefault(combo, []).append((i, acts))
    result = {}
    for combo in itertools.product([YES, NO], repeat=len(table.conditions)):
        hits = cover.get(combo, [])
        if not hits:
            result[combo] = ("gap", None, [])
        elif len({a for _, a in hits}) > 1:
            result[combo] = ("conflict", None, [i for i, _ in hits])
        else:
            result[combo] = ("ok", hits[0][1], [i for i, _ in hits])
    return result


def redundant_rules(table):
    """Rules whose every combination is already handled identically by earlier rules."""
    out = []
    seen = {}
    for i, (vals, acts) in enumerate(table.rules, 1):
        combos = expand(vals)
        if all(seen.get(c) == acts for c in combos):
            out.append(i)
        for c in combos:
            seen.setdefault(c, acts)
    return out


def collapse(table, result):
    """Merge defined combinations with equal outcomes into rules using don't-cares."""
    by_action = {}
    for combo, (status, acts, _) in result.items():
        if status == "ok":
            by_action.setdefault(acts, []).append(combo)
    collapsed = []
    for acts, combos in by_action.items():
        terms = {tuple(c) for c in combos}
        primes = set()
        while terms:
            merged, used = set(), set()
            tl = sorted(terms)
            for a, b in itertools.combinations(tl, 2):
                diff = [k for k in range(len(a)) if a[k] != b[k]]
                if len(diff) == 1 and ANY not in (a[diff[0]], b[diff[0]]):
                    merged.add(a[:diff[0]] + (ANY,) + a[diff[0] + 1:])
                    used |= {a, b}
            primes |= {t for t in terms if t not in used}
            terms = merged
        # greedy cover of the original combos with the prime terms
        remaining, chosen = set(combos), []
        while remaining:
            best = max(primes, key=lambda p: (len(set(expand(p)) & remaining), p.count(ANY)))
            gain = set(expand(best)) & remaining
            if not gain:
                break
            chosen.append(best)
            remaining -= gain
        for term in chosen:
            collapsed.append((term, acts))
    collapsed.sort(key=lambda r: ["".join(r[0])], reverse=False)
    return collapsed


# ---------- rendering ----------
def tabulate(header, rows, fmt):
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
        return buf.getvalue().rstrip("\n")
    if fmt == "markdown":
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
        return "\n".join(lines)
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)]
    line = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip()
    return "\n".join([line(header), "  ".join("-" * w for w in widths), *map(line, rows)])


def acts_text(table, acts):
    names = table.ordered(acts)
    return ", ".join(names) if names else "(no action)"


def main():
    p = argparse.ArgumentParser(description="Decision table test generator")
    p.add_argument("input", help="Path to a rules file, or the word: demo")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--full-table", action="store_true", help="Show every condition combination and its outcome")
    mode.add_argument("--collapse", action="store_true", help="Show the rules collapsed with don't-cares")
    p.add_argument("--expand-dc", action="store_true", help="Make one test per concrete combination, not per rule")
    p.add_argument("--include-gaps", action="store_true", help="Add a test row for each undefined combination")
    p.add_argument("--format", choices=["text", "markdown", "csv"], default="text")
    p.add_argument("--output", help="Write to a file instead of printing")
    args = p.parse_args()

    if args.input == "demo":
        text = DEMO
    else:
        path = Path(args.input)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        text = path.read_text(encoding="utf-8-sig")

    table = Table(text)
    result = evaluate(table)
    conds = table.conditions
    gaps = [c for c, (s, _, _) in result.items() if s == "gap"]
    conflicts = [(c, r) for c, (s, _, r) in result.items() if s == "conflict"]
    redundant = redundant_rules(table)

    if args.full_table:
        header = ["#"] + conds + ["Outcome"]
        rows = []
        for i, (combo, (status, acts, rule_nums)) in enumerate(result.items(), 1):
            outcome = acts_text(table, acts) if status == "ok" else (
                "UNDEFINED (no rule)" if status == "gap" else f"CONFLICT (rules {', '.join(map(str, rule_nums))})")
            rows.append([str(i)] + list(combo) + [outcome])
        out = tabulate(header, rows, args.format)
    elif args.collapse:
        rules = collapse(table, result)
        rows = [[str(i)] + list(t) + [acts_text(table, a)] for i, (t, a) in enumerate(rules, 1)]
        out = tabulate(["Rule"] + conds + ["Outcome"], rows, args.format)
    else:
        rows, n = [], 0
        for i, (vals, acts) in enumerate(table.rules, 1):
            if args.expand_dc:
                for combo in expand(vals):
                    n += 1
                    rows.append([f"DT-{n:02d}"] + list(combo) + [acts_text(table, acts)])
            else:
                n += 1
                shown = [v if v != ANY else "Y or N" for v in vals]
                rows.append([f"DT-{n:02d}"] + shown + [acts_text(table, acts)])
        if args.include_gaps:
            for k, combo in enumerate(gaps, 1):
                rows.append([f"DT-G{k:02d}"] + list(combo) + ["UNDEFINED: confirm expected behavior with the product owner"])
        out = tabulate(["Test ID"] + conds + ["Expected actions"], rows, args.format)

    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(out)

    total = 2 ** len(conds)
    print(f"\n{len(conds)} conditions, {total} possible combinations, {len(table.rules)} rules.", file=sys.stderr)
    if gaps:
        print(f"Warning: {len(gaps)} undefined combination(s):", file=sys.stderr)
        for c in gaps[:8]:
            print("   " + ", ".join(f"{n}={v}" for n, v in zip(conds, c)), file=sys.stderr)
        if len(gaps) > 8:
            print(f"   ...and {len(gaps) - 8} more (use --full-table)", file=sys.stderr)
    for c, rule_nums in conflicts[:8]:
        print("Warning: conflict for " + ", ".join(f"{n}={v}" for n, v in zip(conds, c))
              + f" (rules {', '.join(map(str, rule_nums))} disagree)", file=sys.stderr)
    if redundant:
        print(f"Note: rule(s) {', '.join(map(str, redundant))} are redundant.", file=sys.stderr)
    if not gaps and not conflicts:
        print("Rules are complete and consistent.", file=sys.stderr)


if __name__ == "__main__":
    main()
