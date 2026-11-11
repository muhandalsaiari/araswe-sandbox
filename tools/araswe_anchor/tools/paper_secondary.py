"""PREREG Part 1 secondary metric: turns to first gold-file read, capped at 31. Standard library only.

usage: python3 -I tools/araswe_anchor/tools/paper_secondary.py [--prefix paper_full]

Written after the primary verdicts were read and before this metric was computed. PREREG does not define "read", so it is
fixed here: a turn is one agent step that makes tool calls, counted from 1. A turn reads a gold file when one of its tool calls
names a non-test gold file path (from the gold patch) in its arguments, through read_file or any other tool except edits and
submit_patch. A run that never does, or has no trace, scores 31. The row used is the primary row (rerun when there is one); a
run that counts as 0 in the primary analysis scores 31. Reported per arm with paired differences for the H1 to H4 contrasts
and a two-sided Wilcoxon p, no verdicts: PREREG names no test for secondary metrics.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper_read import NAMES, ROOT, gold_files, ledger_rows, pick, wilcoxon  # noqa: E402

CAP = 31
EDIT = ("edit", "write", "replace", "patch", "insert", "create", "submit")


def calls(step):
    for c in step.get("tool_calls") or []:
        name = str(c.get("function_name") or c.get("name") or "")
        args = c.get("arguments")
        yield name, args if isinstance(args, str) else json.dumps(args or {})


def first_read(row, gold):
    if row is None or not row.get("trace"):
        return CAP
    p = ROOT / row["trace"]
    if not p.exists():
        return CAP
    turn = 0
    for step in json.load(open(p, errors="replace")).get("steps", []):
        if not step.get("tool_calls"):
            continue
        turn += 1
        if turn >= CAP:
            return CAP
        for name, args in calls(step):
            if any(w in name.lower() for w in EDIT):
                continue
            if any(g in args for g in gold):
                return turn
    return CAP


def main(argv):
    prefix = argv[argv.index("--prefix") + 1] if "--prefix" in argv else "paper_full"
    rows, gold = ledger_rows(prefix), gold_files()
    tasks = sorted(set.intersection(*[set(rows.get(f"{prefix}_{n}", {})) for n in NAMES]))
    T = {}
    for n in NAMES:
        T[n] = [first_read(pick(rows, prefix, n, t)[0], gold[t]) for t in tasks]
        never = sum(x == CAP for x in T[n])
        print(f"{n:10s} mean {sum(T[n]) / len(tasks):5.1f}  median {sorted(T[n])[len(tasks) // 2]:2d}  capped {never}/{len(tasks)}")
    for h, a, b in (("H1 AR - EN", "ar", "en"), ("H2 EN+anchor - EN", "en_anchor", "en"),
                    ("H4 AR+anchor - AR+TF", "ar_anchor", "ar_tf")):
        d = [x - y for x, y in zip(T[a], T[b])]
        print(f"{h:22s} mean diff {sum(d) / len(d):+5.1f} turns, Wilcoxon p {wilcoxon(T[a], T[b]):.4f}")
    did = [(ar - en) - (ara - ena) for en, ar, ena, ara in zip(T["en"], T["ar"], T["en_anchor"], T["ar_anchor"])]
    print(f"H3 (AR-EN) - (AR+anchor - EN+anchor) mean {sum(did) / len(did):+5.1f} turns")
    out = ROOT / "runs" / prefix / "secondary_turns.json"
    out.write_text(json.dumps({"n": len(tasks), "cap": CAP, "per_arm": {n: T[n] for n in NAMES}, "tasks": tasks}))


if __name__ == "__main__":
    main(sys.argv[1:])
