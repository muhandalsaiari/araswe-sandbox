"""Paired test on Exp A per-task CSVs: is a top-3 difference real or noise?

usage: python3 -I tools/araswe_anchor/tools/paired_test.py A.csv B.csv [--rankers r1,r2,...] [--k 3]
       python3 -I tools/araswe_anchor/tools/paired_test.py A.csv --vs anchor [--k 3]

Two CSVs (e.g. English vs Arabic): for each ranker, compares top-k hits task by task.
One CSV with --vs R: compares every other ranker against R on the same tasks.
Per comparison prints: hit rates, the paired difference with a 95% bootstrap CI over tasks,
the discordant counts (hit in one, miss in the other) and an exact McNemar p-value.
Inputs are eval_localization.py's <label>_per_task.csv (rank per task, empty = miss).
"""
import csv
import random
import sys
from math import comb


def load(path):
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["instance_id"]: r for r in rows}, [c for c in rows[0] if c not in ("instance_id", "repo", "anchor_blind")]


def hit(row, ranker, k):
    v = (row.get(ranker) or "").strip()
    return bool(v) and int(float(v)) <= k


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def boot_ci(diffs, reps=10000, seed=0):
    rnd, n = random.Random(seed), len(diffs)
    means = sorted(sum(diffs[rnd.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def compare(label, xs, ys):
    n = len(xs)
    b = sum(x and not y for x, y in zip(xs, ys))
    c = sum(y and not x for x, y in zip(xs, ys))
    diffs = [int(x) - int(y) for x, y in zip(xs, ys)]
    lo, hi = boot_ci(diffs)
    print("%-34s %5.0f%% %5.0f%% %+6.1f [%+5.1f, %+5.1f] %5d %5d %8.3f" % (
        label, 100 * sum(xs) / n, 100 * sum(ys) / n, 100 * (b - c) / n, 100 * lo, 100 * hi, b, c, mcnemar_exact(b, c)))


def main(argv):
    k = int(argv[argv.index("--k") + 1]) if "--k" in argv else 3
    vs = argv[argv.index("--vs") + 1] if "--vs" in argv else None
    only = argv[argv.index("--rankers") + 1].split(",") if "--rankers" in argv else None
    files = [a for a in argv if a.endswith(".csv")]
    print("%-34s %6s %6s %6s %16s %5s %5s %8s" % ("comparison (top-%d)" % k, "A", "B", "A-B", "95% CI", "A>B", "B>A", "p"))
    if vs:
        rows, rankers = load(files[0])
        ids = sorted(rows)
        print("tasks: %d" % len(ids))
        for r in rankers:
            if r == vs or (only and r not in only):
                continue
            compare("%s vs %s" % (r, vs), [hit(rows[i], r, k) for i in ids], [hit(rows[i], vs, k) for i in ids])
    else:
        (ra, rka), (rb, rkb) = load(files[0]), load(files[1])
        ids = sorted(set(ra) & set(rb))
        print("tasks in both: %d (A only %d, B only %d)" % (len(ids), len(set(ra) - set(rb)), len(set(rb) - set(ra))))
        for r in rka:
            if r not in rkb or (only and r not in only):
                continue
            compare(r, [hit(ra[i], r, k) for i in ids], [hit(rb[i], r, k) for i in ids])


if __name__ == "__main__":
    main(sys.argv[1:])
