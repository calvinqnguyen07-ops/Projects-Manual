#!/usr/bin/env python3
"""
qa_risk_priority.py - Risk-based test prioritization for manual QA.

You never have time to test everything. Score each feature, and this tool ranks
them by risk, splits your testing hours accordingly, recommends how deep to test
each one, and flags features that have too few (or too many) tests for their risk.
No dependencies (Python 3.8+).

Score every feature from 1 (low) to 5 (high):
    impact      how bad is it for users/business if this breaks?
    complexity  how complicated is the feature or its code?
    change      how much has it changed recently?
    defects     how many bugs has it had historically?
    tests       (optional) how many test cases you already have for it

Risk = impact x likelihood, where likelihood is a weighted mix of
complexity, change and defects. Risk ranges from 1 to 25.

Usage examples:
    python qa_risk_priority.py demo --hours 40
    python qa_risk_priority.py --template > features.csv
    python qa_risk_priority.py features.csv --hours 24
    python qa_risk_priority.py features.csv --format markdown --output plan.md
    python qa_risk_priority.py features.csv --weights 0.2,0.5,0.3
"""

import argparse
import csv
import io
import sys
from pathlib import Path

DEMO_CSV = """\
feature,impact,complexity,change,defects,tests
Checkout & payment,5,5,4,4,12
Login & authentication,5,3,2,3,15
Shopping cart,4,3,4,4,8
Product search,4,4,3,2,6
Order history,3,2,1,1,10
User profile settings,2,2,3,2,9
Wishlist,2,2,2,1,7
Newsletter signup,1,1,1,1,6
Admin reporting,3,4,5,3,2
"""

TEMPLATE = "feature,impact,complexity,change,defects,tests\nExample feature,4,3,2,3,10\n"

LEVELS = [
    (16, "Critical", "Full functional + negative + boundary tests, exploratory session, full regression every build"),
    (10, "High", "Full functional + key negative tests, regression every release"),
    (5, "Medium", "Main flows + a few negative checks, regression when touched"),
    (0, "Low", "Quick smoke test only, test when time allows"),
]


# ---------- loading ----------
def parse_score(value, field, feature):
    try:
        n = int(str(value).strip())
    except ValueError:
        sys.exit(f"Feature '{feature}': {field} must be a whole number 1-5 (got '{value}').")
    if not 1 <= n <= 5:
        sys.exit(f"Feature '{feature}': {field} must be between 1 and 5 (got {n}).")
    return n


def load_features(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        sys.exit("CSV is empty.")
    cols = {c.strip().lower(): c for c in reader.fieldnames}
    for needed in ["feature", "impact", "complexity", "change", "defects"]:
        if needed not in cols:
            sys.exit(f"CSV is missing the '{needed}' column. Expected: feature,impact,complexity,change,defects[,tests]")
    features = []
    for row in reader:
        name = (row[cols["feature"]] or "").strip()
        if not name:
            continue
        tests_raw = (row.get(cols.get("tests", ""), "") or "").strip()
        tests = None
        if tests_raw:
            if not tests_raw.isdigit():
                sys.exit(f"Feature '{name}': tests must be a whole number (got '{tests_raw}').")
            tests = int(tests_raw)
        features.append({
            "feature": name,
            "impact": parse_score(row[cols["impact"]], "impact", name),
            "complexity": parse_score(row[cols["complexity"]], "complexity", name),
            "change": parse_score(row[cols["change"]], "change", name),
            "defects": parse_score(row[cols["defects"]], "defects", name),
            "tests": tests,
        })
    if not features:
        sys.exit("No features found in the CSV.")
    return features


# ---------- scoring ----------
def level_for(risk):
    for threshold, name, advice in LEVELS:
        if risk >= threshold:
            return name, advice
    return LEVELS[-1][1], LEVELS[-1][2]


def analyze(features, weights, hours):
    wc, wch, wd = weights
    for f in features:
        f["likelihood"] = f["complexity"] * wc + f["change"] * wch + f["defects"] * wd
        f["risk"] = f["impact"] * f["likelihood"]
        f["level"], f["advice"] = level_for(f["risk"])
    features.sort(key=lambda f: (-f["risk"], -f["impact"], f["feature"]))

    total_risk = sum(f["risk"] for f in features)
    for f in features:
        f["share"] = f["risk"] / total_risk
        f["hours"] = hours * f["share"] if hours else None

    have_tests = all(f["tests"] is not None for f in features)
    if have_tests:
        total_tests = sum(f["tests"] for f in features)
        for f in features:
            expected = f["share"] * total_tests
            f["expected_tests"] = expected
            if total_tests == 0:
                f["gap"] = "-"
            elif f["tests"] < expected * 0.7:
                f["gap"] = "UNDER-TESTED"
            elif f["tests"] > expected * 1.5 and f["level"] in ("Low", "Medium"):
                f["gap"] = "over-tested"
            else:
                f["gap"] = "ok"
    return have_tests


# ---------- rendering ----------
def render(features, hours, have_tests, fmt):
    header = ["Rank", "Feature", "Impact", "Likelihood", "Risk", "Level"]
    if hours:
        header.append("Hours")
    if have_tests:
        header += ["Tests", "Suggested", "Gap"]
    header.append("Recommended depth")

    rows = []
    for i, f in enumerate(features, 1):
        r = [str(i), f["feature"], str(f["impact"]), f"{f['likelihood']:.1f}", f"{f['risk']:.1f}", f["level"]]
        if hours:
            r.append(f"{f['hours']:.1f}")
        if have_tests:
            r += [str(f["tests"]), f"{f['expected_tests']:.0f}", f["gap"]]
        r.append(f["advice"])
        rows.append(r)

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
        return buf.getvalue().rstrip("\n")
    if fmt == "markdown":
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(lines)

    # text: keep the long advice column out of the table and list it underneath
    short_header, short_rows = header[:-1], [r[:-1] for r in rows]
    widths = [max(len(x) for x in col) for col in zip(short_header, *short_rows)]
    line = lambda r: "  ".join(x.ljust(w) for x, w in zip(r, widths)).rstrip()
    out = [line(short_header), "  ".join("-" * w for w in widths), *map(line, short_rows), "", "Recommended depth:"]
    seen = set()
    for _, name, advice in LEVELS[:]:
        if any(f["level"] == name for f in features) and name not in seen:
            out.append(f"  {name:<9} {advice}")
            seen.add(name)
    return "\n".join(out)


def summary(features, hours, have_tests):
    lines = []
    counts = {}
    for f in features:
        counts[f["level"]] = counts.get(f["level"], 0) + 1
    lines.append("Levels: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: [l[1] for l in LEVELS].index(kv[0]))))
    if hours:
        top = [f for f in features if f["level"] in ("Critical", "High")]
        share = sum(f["hours"] for f in top) / hours * 100
        lines.append(f"Critical + High features get {share:.0f}% of your {hours:g} hours.")
    if have_tests:
        under = [f["feature"] for f in features if f["gap"] == "UNDER-TESTED"]
        over = [f["feature"] for f in features if f["gap"] == "over-tested"]
        if under:
            lines.append("Add tests for: " + ", ".join(under))
        if over:
            lines.append("Consider trimming tests for: " + ", ".join(over))
    return lines


# ---------- CLI ----------
def main():
    p = argparse.ArgumentParser(description="Risk-based test prioritization")
    p.add_argument("input", nargs="?", help="Path to a features CSV, or the word: demo")
    p.add_argument("--hours", type=float, help="Total testing hours to split across features")
    p.add_argument("--weights", default="0.3,0.3,0.4",
                   help="Likelihood weights for complexity,change,defects (default 0.3,0.3,0.4)")
    p.add_argument("--format", choices=["text", "markdown", "csv"], default="text")
    p.add_argument("--template", action="store_true", help="Print a blank CSV template and exit")
    p.add_argument("--output", help="Write to a file instead of printing")
    args = p.parse_args()

    if args.template:
        print(TEMPLATE, end="")
        return
    if not args.input:
        p.print_help()
        sys.exit(1)

    try:
        weights = [float(x) for x in args.weights.split(",")]
        assert len(weights) == 3 and all(w >= 0 for w in weights) and sum(weights) > 0
    except (ValueError, AssertionError):
        sys.exit("--weights needs three non-negative numbers, e.g. 0.3,0.3,0.4")
    total = sum(weights)
    weights = [w / total for w in weights]  # normalize so likelihood stays on the 1-5 scale

    if args.hours is not None and args.hours <= 0:
        sys.exit("--hours must be greater than zero.")

    if args.input == "demo":
        text = DEMO_CSV
    else:
        path = Path(args.input)
        if not path.exists():
            sys.exit(f"File not found: {path}")
        text = path.read_text(encoding="utf-8-sig")

    features = load_features(text)
    have_tests = analyze(features, weights, args.hours)
    result = render(features, args.hours, have_tests, args.format)

    if args.output:
        Path(args.output).write_text(result + "\n", encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(result)
    print("", file=sys.stderr)
    for line in summary(features, args.hours, have_tests):
        print(line, file=sys.stderr)


if __name__ == "__main__":
    main()
