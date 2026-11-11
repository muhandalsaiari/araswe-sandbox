"""PREREG Part 2 analysis: S1 to S3 and their verdicts, from runs/part2. Standard library only. Prints ids-free numbers.

usage: python3 -I tools/araswe_anchor/tools/part2_read.py [--data ~/araswe/sbrest] [--runs runs/part2]

Written before any Part 2 number was read. Task score: findfile_nolist top-3 hit in each language minus hit in English, mean over six
languages, in points. A task is out of the analysis when eval_localization could not score it in English (no gold file in the snapshot).

Bootstrap: repos resampled with replacement inside each stratum, then tasks inside each drawn repo, 10,000 draws, seed 42.

Choices PREREG leaves open, fixed here before reading:
- S1 = small minus large. S2 = prose-hit tasks minus others, S3 = fewer-identifier half minus the rest, each inside each stratum,
  so 5 rows. A loss is negative, so the prediction is a negative difference in every row.
- Holm runs over those 5 rows; p is two-sided from the bootstrap. HOLDS needs the 95% interval below zero and Holm p under 0.05.
- S2 and S3 as a whole HOLD only if a row holds in both strata.
- Bare identifiers per task: ident parts from signal_audit.kind on the English issue. Fewer = at or below the stratum median.
"""
import csv
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from signal_audit import kind  # noqa: E402
from translate_issues import mask  # noqa: E402

LANGS = ["ar", "hi", "zh", "ru", "es", "fr"]
M, B, SEED = "findfile_nolist", 10000, 42


def load(p):
    return {r["instance_id"]: r for r in csv.DictReader(open(p))}


def hit(r):
    v = r[M]
    return int(v not in ("", "None") and 0 < int(float(v)) <= 3)


def group(rows, flag, rng_key=None):
    """rows: list of task dicts. flag: None, or a function; the statistic is mean(flag) - mean(not flag), or the mean."""
    def stat(sample):
        if flag is None:
            return sum(t["d"] for t in sample) / len(sample) if sample else None
        a = [t["d"] for t in sample if flag(t)]
        b = [t["d"] for t in sample if not flag(t)]
        return sum(a) / len(a) - sum(b) / len(b) if a and b else None
    return stat


def draw(rng, tasks):
    by = defaultdict(list)
    for t in tasks:
        by[t["repo"]].append(t)
    out = []
    for r in rng.choices(sorted(by), k=len(by)):
        out += rng.choices(by[r], k=len(by[r]))
    return out


def interval(obs, draws):
    d = sorted(draws)
    q = lambda f: d[min(len(d) - 1, int(f * len(d)))]  # noqa: E731
    p = min(1.0, 2 * min(sum(x <= 0 for x in d), sum(x >= 0 for x in d)) / len(d) + 1 / len(d))
    return dict(mean=obs, lo95=q(.025), hi95=q(.975), lo90=q(.05), hi90=q(.95), p=p, valid=len(d))


def main(argv):
    data = Path(os.path.expanduser(argv[argv.index("--data") + 1] if "--data" in argv else "~/araswe/sbrest"))
    runs = Path(argv[argv.index("--runs") + 1] if "--runs" in argv else "runs/part2")
    strata = load(data / "strata.csv")
    issues = {json.loads(x)["instance_id"]: json.loads(x) for x in open(data / "tasks.jsonl")}
    en = load(runs / "en/en_per_task.csv")
    code = load(runs / "no_prose/no_prose_per_task.csv")
    V = {l: load(runs / f"{l}_mix/{l}_mix_per_task.csv") for l in LANGS}
    tasks = []
    for i, r in en.items():
        if i not in strata or any(i not in V[l] for l in LANGS) or i not in code:
            continue
        e = hit(r)
        parts = mask(issues[i]["problem_statement"])[1]
        tasks.append(dict(id=i, repo=strata[i]["repo"], s=strata[i]["stratum"], en=e, d=100 * sum(hit(V[l][i]) - e for l in LANGS) / 6,
                          prose=int(e == 1 and hit(code[i]) == 0), ident=sum(kind(p) == "ident" for p in parts)))
    S = {s: [t for t in tasks if t["s"] == s] for s in ("small", "large")}
    med = {}
    for s, ts in S.items():
        v = sorted(t["ident"] for t in ts)
        med[s] = v[len(v) // 2]
        for t in ts:
            t["few"] = int(t["ident"] <= med[s])
        print(f"{s}: n={len(ts)} repos={len({t['repo'] for t in ts})} EN top-3 {100 * sum(t['en'] for t in ts) / len(ts):.1f}, "
              f"mean change {sum(t['d'] for t in ts) / len(ts):+.1f}, prose-hit tasks {sum(t['prose'] for t in ts)}, "
              f"median idents {med[s]}, few-half {sum(t['few'] for t in ts)}")
        print("   by language: " + " ".join(f"{l} {100 * sum(hit(V[l][t['id']]) - t['en'] for t in ts) / len(ts):+.1f}" for l in LANGS))

    rng = random.Random(SEED)
    mean = lambda x: sum(t["d"] for t in x) / len(x)  # noqa: E731
    diff = lambda f: group(None, f)  # noqa: E731
    rows = {}
    d = [mean(draw(rng, S["small"])) - mean(draw(rng, S["large"])) for _ in range(B)]
    rows["S1"] = interval(mean(S["small"]) - mean(S["large"]), d)
    for s in S:
        for name, f in (("S2", lambda t: t["prose"]), ("S3", lambda t: t["few"])):
            st = diff(f)
            d = [x for x in (st(draw(rng, S[s])) for _ in range(B)) if x is not None]
            rows[f"{name}_{s}"] = interval(st(S[s]), d)
    order = sorted(rows, key=lambda k: rows[k]["p"])
    run = 0.0
    for k, h in enumerate(order):
        run = max(run, min(1.0, (len(order) - k) * rows[h]["p"]))
        rows[h]["p_holm"] = run
    for k, v in rows.items():
        v["verdict"] = ("HOLDS" if v["hi95"] < 0 and v["p_holm"] < .05 else
                        "FAILS" if -3 < v["lo90"] and v["hi90"] < 3 else "NOT SHOWN")
        print(f"{k:9s} {v['verdict']:9s} {v['mean']:+.1f} pts, 95% [{v['lo95']:+.1f}, {v['hi95']:+.1f}], 90% [{v['lo90']:+.1f}, {v['hi90']:+.1f}], "
              f"p {v['p']:.4f}, Holm {v['p_holm']:.4f}, draws {v['valid']}")
    for n in ("S2", "S3"):
        a, b = rows[f"{n}_small"]["verdict"], rows[f"{n}_large"]["verdict"]
        print(n, "overall:", "HOLDS" if a == b == "HOLDS" else "FAILS" if a == b == "FAILS" else "NOT SHOWN")
    # Exploratory, not in PREREG. S2 as registered compares tasks that hit in English (they can only lose) with a group that includes
    # English misses (they can only gain), so it leans toward HOLDS by construction. This row compares English hits only.
    print("EXPLORATORY S2 among English hits only (prose-hit minus other hits):")
    for s in S:
        hits = [t for t in S[s] if t["en"]]
        st = diff(lambda t: t["prose"])
        d = [x for x in (st(draw(rng, hits)) for _ in range(B)) if x is not None]
        v = interval(st(hits), d)
        rows[f"explore_S2_{s}"] = {**v, "verdict": "exploratory"}
        print(f"  {s}: n={len(hits)} {v['mean']:+.1f} pts, 95% [{v['lo95']:+.1f}, {v['hi95']:+.1f}]")
    (runs / "verdicts.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
