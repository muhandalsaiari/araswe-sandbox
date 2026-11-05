"""Draw the paper's agent-study tasks: 60 stratified by repo, seed 42, then a pilot of 8 from the rest (plan v5 section 5.4).

usage: python3 -I tools/araswe_anchor/tools/select_tasks.py <out_dir>     (run from the repo root)

Writes tasks_60.txt and pilot_8.txt, one id per line. The pilot never overlaps the 60, so full-run tasks stay unseen.
"""
import csv
import os
import random
import sys


def draw(pool, n, rng):
    """Largest-remainder share of n per repo, then a seeded sample inside each repo."""
    total = sum(len(v) for v in pool.values())
    share = {k: n * len(v) / total for k, v in pool.items()}
    take = {k: int(s) for k, s in share.items()}
    for k in sorted(share, key=lambda k: (share[k] - take[k], k), reverse=True)[:n - sum(take.values())]:
        take[k] += 1
    return {k: rng.sample(sorted(pool[k]), take[k]) for k in sorted(pool)}


def main(out):
    pool = {}
    for r in csv.DictReader(open("tasks/manifest.csv")):
        if r["source"] == "kaggle-public" and r["split"] != "excluded":
            pool.setdefault(r["repo"], []).append(r["id"])
    print("usable", sum(len(v) for v in pool.values()), {k: len(v) for k, v in pool.items()})
    rng = random.Random(42)
    main_set = draw(pool, 60, rng)
    rest = {k: [t for t in v if t not in main_set[k]] for k, v in pool.items()}
    pilot = draw({k: v for k, v in rest.items() if v}, 8, rng)
    os.makedirs(out, exist_ok=True)
    for name, d in (("tasks_60.txt", main_set), ("pilot_8.txt", pilot)):
        ids = [t for k in sorted(d) for t in d[k]]
        open(os.path.join(out, name), "w").write("\n".join(ids) + "\n")
        print(name, len(ids), {k: len(v) for k, v in d.items()})


if __name__ == "__main__":
    main(sys.argv[1])
