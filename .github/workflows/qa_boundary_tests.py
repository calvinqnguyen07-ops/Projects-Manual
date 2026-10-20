#!/usr/bin/env python3
"""
qa_boundary_tests.py - Boundary value analysis and equivalence partitioning
test generator for manual QA.

Describe the input fields of a form or API and get ready-to-run test inputs:
the classic boundary values (min-1, min, min+1, nominal, max-1, max, max+1),
plus the invalid classes people forget (blank, non-numeric, not in list, bad dates).
It can also build full multi-field test cases using the single-fault method
(everything valid except one field at a time). No dependencies (Python 3.8+).

Fields file format (plain text):
    # comments start with a hash
    Age: int 18..65
    Username: length 3..20
    Discount %: decimal 0..100 step 0.5
    Start date: date 2026-01-01..2026-12-31
    Plan: enum Free, Pro, Enterprise
    Referral code: length 0..8 optional

Types: int, decimal (optional 'step N', default 0.01), length (characters),
       date (YYYY-MM-DD), enum (comma-separated list)
Fields are required unless you add 'optional' at the end of the line.

Usage examples:
    python qa_boundary_tests.py demo
    python qa_boundary_tests.py fields.txt
    python qa_boundary_tests.py fields.txt --mode single-fault
    python qa_boundary_tests.py fields.txt --format markdown --output tests.md
    python qa_boundary_tests.py fields.txt --mode single-fault --format csv --full-strings
"""

import argparse
import csv
import io
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

DEMO = """\
# Sign-up form
Age: int 18..65
Username: length 3..20
Discount %: decimal 0..100 step 0.5
Start date: date 2026-01-01..2026-12-31
Plan: enum Free, Pro, Enterprise
Referral code: length 0..8 optional
"""

NOTES = []  # messages about assumptions made while parsing

RANGE_RE = re.compile(r"^(-?[\d.]+?)\s*\.\.\s*(-?[\d.]+?)(?:\s+step\s+(\S+))?$")
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})$")


# ---------- parsing ----------
class Field:
    def __init__(self, name, kind, optional, lo=None, hi=None, step=None, values=None):
        self.name, self.kind, self.optional = name, kind, optional
        self.lo, self.hi, self.step, self.values = lo, hi, step, values or []


def parse_fields(text):
    fields = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            sys.exit(f"Line {n}: expected 'Name: type spec' (got '{raw.strip()}').")
        name, rest = (s.strip() for s in line.split(":", 1))
        optional = bool(re.search(r"\s+optional$", rest, re.I))
        if optional:
            rest = re.sub(r"\s+optional$", "", rest, flags=re.I)
        parts = rest.split(None, 1)
        if not name or not parts:
            sys.exit(f"Line {n}: expected 'Name: type spec' (got '{raw.strip()}').")
        kind, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        if any(f.name == name for f in fields):
            sys.exit(f"Line {n}: duplicate field name '{name}'.")
        try:
            if kind in ("int", "length"):
                m = RANGE_RE.match(arg)
                if not m or m.group(3):
                    raise ValueError(f"'{kind}' needs a range like 1..10")
                lo, hi = int(m.group(1)), int(m.group(2))
                if kind == "length" and lo < 0:
                    raise ValueError("length can't be negative")
                fields.append(Field(name, kind, optional, lo, hi))
            elif kind == "decimal":
                m = RANGE_RE.match(arg)
                if not m:
                    raise ValueError("'decimal' needs a range like 0..100 and optional 'step 0.5'")
                step = Decimal(m.group(3) or "0.01")
                if step <= 0:
                    raise ValueError("step must be greater than zero")
                fields.append(Field(name, kind, optional, Decimal(m.group(1)), Decimal(m.group(2)), step))
            elif kind == "date":
                m = DATE_RE.match(arg)
                if not m:
                    raise ValueError("'date' needs a range like 2026-01-01..2026-12-31")
                lo = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                hi = datetime.strptime(m.group(2), "%Y-%m-%d").date()
                fields.append(Field(name, kind, optional, lo, hi))
            elif kind == "enum":
                values = [v.strip() for v in arg.split(",") if v.strip()]
                if not values:
                    raise ValueError("'enum' needs a comma-separated list")
                if len(set(values)) != len(values):
                    raise ValueError("enum has duplicate values")
                fields.append(Field(name, kind, optional, values=values))
            else:
                raise ValueError(f"unknown type '{kind}' (use int, decimal, length, date, enum)")
            f = fields[-1]
            if f.kind != "enum" and f.lo > f.hi:
                raise ValueError("minimum is greater than maximum")
            if f.kind == "length" and f.lo == 0 and not f.optional:
                f.optional = True  # a minimum length of 0 means an empty value is allowed
                NOTES.append(f"'{f.name}' has minimum length 0, so it is treated as optional (blank is valid).")
        except (ValueError, InvalidOperation) as e:
            sys.exit(f"Line {n}: {e}")
    if not fields:
        sys.exit("No fields found.")
    return fields


# ---------- test point generation ----------
def places(step):
    return max(0, -step.as_tuple().exponent)


def cases_for(f):
    """Return a list of dicts: label, technique, input, display, valid, reason. First nominal case is the baseline."""
    raw = []  # (label, technique, input_string, display, valid, reason)

    def add(label, tech, inp, valid, reason="", display=None):
        raw.append((label, tech, inp, display if display is not None else (inp if inp != "" else "(blank)"), valid, reason))

    if f.kind in ("int", "decimal"):
        if f.kind == "int":
            step, fmt = 1, str
            nominal = (f.lo + f.hi) // 2
        else:
            step = f.step
            p = places(step)
            fmt = lambda v: f"{v:.{p}f}"
            mid = (f.lo + f.hi) / 2
            nominal = (mid / step).to_integral_value() * step
            nominal = min(max(nominal, f.lo), f.hi)
        points = [("min-1", f.lo - step), ("min", f.lo), ("min+1", f.lo + step), ("nominal", nominal),
                  ("max-1", f.hi - step), ("max", f.hi), ("max+1", f.hi + step)]
        for label, v in points:
            ok = f.lo <= v <= f.hi
            add(label, "EP" if label == "nominal" else "BVA", fmt(v), ok, "" if ok else ("below min" if v < f.lo else "above max"))
        add("non-numeric text", "EP", "abc", False, "not a number")
        if f.kind == "int":
            add("decimal instead of whole number", "EP", f"{nominal}.5", False, "not a whole number")
        add("blank", "EP", "", f.optional, "" if f.optional else "required")

    elif f.kind == "length":
        nominal = (f.lo + f.hi) // 2
        points = [("min-1", f.lo - 1), ("min", f.lo), ("min+1", f.lo + 1), ("nominal", nominal),
                  ("max-1", f.hi - 1), ("max", f.hi), ("max+1", f.hi + 1)]
        for label, n in points:
            if n < 0:
                continue
            ok = f.lo <= n <= f.hi or (n == 0 and f.optional)
            if ok:
                reason = ""
            else:
                reason = "too short" if n < f.lo else "too long"
                if n == 0:
                    reason = "required"
            disp = "(blank)" if n == 0 else (repr("a" * n) if n <= 12 else f"'a' x {n}")
            add(f"{label} ({n} chars)", "EP" if label == "nominal" else "BVA", "a" * n, ok, reason, disp)
        add("blank", "EP", "", f.optional, "" if f.optional else "required")
        if not f.optional:
            add("spaces only", "EP", "   ", False, "only whitespace", "'   ' (3 spaces)")

    elif f.kind == "date":
        d = timedelta(days=1)
        nominal = f.lo + (f.hi - f.lo) // 2
        points = [("min-1 day", f.lo - d), ("min", f.lo), ("min+1 day", f.lo + d), ("nominal", nominal),
                  ("max-1 day", f.hi - d), ("max", f.hi), ("max+1 day", f.hi + d)]
        for label, v in points:
            ok = f.lo <= v <= f.hi
            add(label, "EP" if label == "nominal" else "BVA", v.isoformat(), ok, "" if ok else ("before min" if v < f.lo else "after max"))
        add("impossible date", "EP", "2025-02-30", False, "invalid date")
        add("not a date", "EP", "not a date", False, "invalid date")
        add("blank", "EP", "", f.optional, "" if f.optional else "required")

    else:  # enum
        for i, v in enumerate(f.values):
            add("nominal (first value)" if i == 0 else "valid value", "EP", v, True)
        add("value not in list", "EP", "NOT_IN_LIST", False, "not in list")
        add("blank", "EP", "", f.optional, "" if f.optional else "required")

    # merge duplicates (tiny ranges make several points identical)
    merged = {}
    for label, tech, inp, disp, ok, reason in raw:
        if inp in merged:
            m = merged[inp]
            m["label"] += f" = {label}"
            if tech == "BVA":
                m["technique"] = "BVA"
        else:
            merged[inp] = {"label": label, "technique": tech, "input": inp, "display": disp, "valid": ok, "reason": reason}
    cases = list(merged.values())
    # keep the baseline first
    for i, c in enumerate(cases):
        if c["valid"] and "nominal" in c["label"]:
            cases.insert(0, cases.pop(i))
            break
    return cases


def baseline(cases):
    return next(c for c in cases if c["valid"])


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


def shown(c, full):
    return c["input"] if (full and c["input"] != "") else c["display"]


def expected(c, prefix=""):
    return "ACCEPT" if c["valid"] else f"REJECT ({prefix}{c['reason']})"


def main():
    p = argparse.ArgumentParser(description="Boundary value and equivalence partition test generator")
    p.add_argument("input", help="Path to a fields file, or the word: demo")
    p.add_argument("--mode", choices=["fields", "single-fault"], default="fields",
                   help="fields: test points per field (default). single-fault: full multi-field test cases")
    p.add_argument("--format", choices=["text", "markdown", "csv"], default="text")
    p.add_argument("--full-strings", action="store_true", help="Show the actual characters of long strings")
    p.add_argument("--output", help="Write to a file instead of printing")
    args = p.parse_args()

    if args.input == "demo":
        text = DEMO
    else:
        path = Path(args.input)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        text = path.read_text(encoding="utf-8-sig")

    fields = parse_fields(text)
    all_cases = {f.name: cases_for(f) for f in fields}

    if args.mode == "fields":
        rows, n = [], 0
        for f in fields:
            for c in all_cases[f.name]:
                n += 1
                rows.append([f"BV-{n:02d}", f.name, c["technique"], c["label"], shown(c, args.full_strings), expected(c)])
        out = tabulate(["ID", "Field", "Technique", "Test point", "Input", "Expected"], rows, args.format)
    else:
        base = {f.name: baseline(all_cases[f.name]) for f in fields}
        rows = [["SF-00", "(none)", "baseline: all fields valid"] + [shown(base[f.name], args.full_strings) for f in fields] + ["ACCEPT"]]
        n = 0
        for f in fields:
            for c in all_cases[f.name]:
                if c["input"] == base[f.name]["input"]:
                    continue
                n += 1
                row = [f"SF-{n:02d}", f.name, c["label"]]
                row += [shown(c if g.name == f.name else base[g.name], args.full_strings) for g in fields]
                row.append(expected(c, prefix=f"{f.name}: "))
                rows.append(row)
        out = tabulate(["ID", "Varied field", "Test point"] + [f.name for f in fields] + ["Expected"], rows, args.format)

    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(out)
    accept = sum(1 for r in rows if r[-1] == "ACCEPT")
    print(f"\n{len(fields)} fields, {len(rows)} test cases ({accept} expect ACCEPT, {len(rows) - accept} expect REJECT).",
          file=sys.stderr)
    for note in NOTES:
        print(f"Note: {note}", file=sys.stderr)
    print("Expected results come from the ranges you gave. Confirm unclear rules (e.g. spaces-only) with the spec.",
          file=sys.stderr)


if __name__ == "__main__":
    main()
