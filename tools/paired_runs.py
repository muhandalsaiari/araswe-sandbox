"""Compare agent runs task by task from the run ledger: which tasks one run solves that the other does not.

usage: python3 -I tools/paired_runs.py <candidate_run_id> <baseline_run_id> [<baseline_run_id> ...] [--ledger results/task_runs.jsonl]

For each baseline, over the tasks both runs have (last ledger row per run and task):
  resolved          tests pass, any time
  resolved_kaggle   tests pass AND the run ended within the Kaggle clock (what the scorer counts)
gained = candidate yes, baseline no; lost = the reverse. p = exact two-sided McNemar (binomial on gained vs
lost). On 20 tasks only a large gap reaches p < 0.05, so read gained/lost task names along with it. Also
prints the mean Kaggle seconds, tool calls and output tokens per run, and a per-task table.
"""
import json
import math
import sys


def mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main(argv):
    ledger, runs, i = "results/task_runs.jsonl", [], 0
    while i < len(argv):
        if argv[i] == "--ledger":
            ledger, i = argv[i + 1], i + 2
        else:
            runs.append(argv[i]); i += 1
    if len(runs) < 2:
        print(__doc__)
        return 2
    rows = {r: {} for r in runs}
    for line in open(ledger):
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if x.get("run_id") in rows:
            rows[x["run_id"]][x["id"]] = x
    for r in runs:
        n = len(rows[r])
        if not n:
            print("%s: no ledger rows" % r)
            continue
        mean = lambda k: sum((v.get(k) or 0) for v in rows[r].values()) / n  # noqa: E731
        print("%-28s tasks %2d  resolved %2d  resolved_kaggle %2d  mean kaggle_s %5.0f  tool_calls %4.1f  out_tokens %6.0f"
              % (r, n, sum(bool(v.get("resolved")) for v in rows[r].values()),
                 sum(bool(v.get("resolved_kaggle")) for v in rows[r].values()),
                 mean("kaggle_s"), mean("tool_calls"), mean("kaggle_out_tokens")))
    cand = runs[0]
    for base in runs[1:]:
        common = sorted(set(rows[cand]) & set(rows[base]))
        for key in ("resolved", "resolved_kaggle"):
            g = [t for t in common if rows[cand][t].get(key) and not rows[base][t].get(key)]
            l = [t for t in common if rows[base][t].get(key) and not rows[cand][t].get(key)]
            print("%s vs %s on %d tasks, %s: gained %d %s, lost %d %s, p=%.2f"
                  % (cand, base, len(common), key, len(g), g, len(l), l, mcnemar(len(g), len(l))))
    tasks = sorted(set().union(*[set(rows[r]) for r in runs]))
    print("\n%-16s " % "task" + " ".join("%-12s" % r[:12] for r in runs) + "   (R = resolved in time, r = resolved after the clock, . = no)")
    for t in tasks:
        cells = []
        for r in runs:
            v = rows[r].get(t)
            cells.append("%-12s" % ("-" if v is None else "R" if v.get("resolved_kaggle") else "r" if v.get("resolved") else "."))
        print("%-16s " % t + " ".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
