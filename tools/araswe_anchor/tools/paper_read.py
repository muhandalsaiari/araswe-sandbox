"""PREREG Part 1 analysis: reads the ledger, prints every pre-registered test and its verdict. Standard library only, no GPU.

usage: python3 -I tools/araswe_anchor/tools/paper_read.py [--prefix paper_full] [--pilot] [--out runs/<prefix>/verdicts.json]

Written before any full-run outcome was seen. --pilot reads the paper_pilot_t0_* rows, only to check the metric code against the
journal's corrected counts (en 4, ar 4, en_anchor 3, ar_anchor 3, ar_tf 3 gold-file edits).

Primary row of a task in an arm: the rerun when there is one, else the first try. A second failure counts as 0. Sensitivity: every
first-try abort counts as 0. Only tasks complete in all five arms are analysed.

Choices PREREG leaves open, fixed here: 90% intervals are paired bootstrap percentile intervals over tasks (10,000 draws, seed 42).
McNemar is two-sided exact and must also point the predicted way. H4's Holm p is the bootstrap share of draws at or below -10 points.
"""
import json
import math
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper_run import ARMS, ROOT, ledger_rows, rerun_reason  # noqa: E402

NAMES = [a[0] for a in ARMS]
B, SEED, MARGIN, ALPHA = 10000, 42, 0.10, 0.05
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*$|_test\.py$|(^|/)conftest\.py$")


def touched(diff):
    return {m for m in re.findall(r"^(?:diff --git a/|--- a/|\+\+\+ b/)(\S+)", diff or "", re.M) if not TEST_PATH.search(m)}


def gold_files():
    out = {}
    for line in open(Path.home() / "araswe/data/tasks.jsonl"):
        r = json.loads(line)
        out[r["instance_id"]] = touched(r["patch"])
    return out


def recall(row, gold):
    if row is None:
        return 0
    p = ROOT / row["patch"] if row.get("patch") else None
    diff = p.read_text(errors="replace") if p and p.exists() else ""
    return int(bool(touched(diff) & gold[row["id"]]))


def tokens(row):
    s = row.get("trace_stats") or {}
    return (s.get("prompt_tokens") or 0) + (s.get("completion_tokens") or 0)


def pick(rows, prefix, name, t):
    """(primary row or None when it counts as 0, first row, was rerun)."""
    first = rows.get(f"{prefix}_{name}", {}).get(t)
    second = rows.get(f"{prefix}_{name}_rerun", {}).get(t)
    if first is None:
        return None, None, False
    if second is None:
        return first, first, False
    return (None if rerun_reason(second) else second), first, True


def mcnemar(a, b):
    """Exact two-sided p for paired 0/1 lists, and the two discordant counts (a only, b only)."""
    x = sum(i and not j for i, j in zip(a, b))
    y = sum(j and not i for i, j in zip(a, b))
    n = x + y
    if not n:
        return 1.0, x, y
    tail = sum(math.comb(n, k) for k in range(min(x, y) + 1)) / 2 ** n
    return min(1.0, 2 * tail), x, y


def boot(d):
    rng = random.Random(SEED)
    n = len(d)
    m = sorted(sum(rng.choices(d, k=n)) / n for _ in range(B))
    return m[int(.05 * B)], m[int(.95 * B) - 1], m


def signflip(d):
    """One-sided p that mean(d) is above 0."""
    rng = random.Random(SEED)
    obs = sum(d) / len(d)
    hits = sum(sum(x if rng.random() < .5 else -x for x in d) / len(d) >= obs - 1e-12 for _ in range(B))
    return (hits + 1) / (B + 1)


def wilcoxon(a, b):
    """Two-sided signed-rank p, normal approximation with tie correction."""
    d = [x - y for x, y in zip(a, b) if x != y]
    n = len(d)
    if not n:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks, i, ties = [0.0] * n, 0, 0.0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        ties += (j - i + 1) ** 3 - (j - i + 1)
        i = j + 1
    w = sum(r for r, x in zip(ranks, d) if x > 0)
    var = n * (n + 1) * (2 * n + 1) / 24 - ties / 48
    z = (w - n * (n + 1) / 4) / math.sqrt(var) if var else 0.0
    return math.erfc(abs(z) / math.sqrt(2))


def holm(ps):
    order = sorted(ps, key=ps.get)
    adj, run = {}, 0.0
    for k, h in enumerate(order):
        run = max(run, min(1.0, (len(order) - k) * ps[h]))
        adj[h] = run
    return adj


def analyse(M):
    """M: {arm: list of 0/1 over the same tasks}. Returns one dict per hypothesis."""
    en, ar, ena, ara, tf = (M[n] for n in NAMES)
    n = len(en)
    h = {}
    p, x, y = mcnemar(en, ar)
    h["H1"] = dict(effect=[j - i for i, j in zip(en, ar)], p=p, right_way=x > y, note=f"EN only {x}, AR only {y}")
    p, x, y = mcnemar(ena, en)
    h["H2"] = dict(effect=[i - j for i, j in zip(ena, en)], p=p, right_way=x > y, note=f"EN+anchor only {x}, EN only {y}")
    did = [(a - b) - (c - d) for a, b, c, d in zip(en, ar, ena, ara)]
    h["H3"] = dict(effect=did, p=signflip(did), right_way=sum(did) > 0, note="(EN-AR) minus (EN+anchor-AR+anchor)")
    d4 = [i - j for i, j in zip(ara, tf)]
    lo, hi, draws = boot(d4)
    h["H4"] = dict(effect=d4, p=max(sum(m <= -MARGIN for m in draws), 1) / B, right_way=True, note="AR+anchor minus AR+TF, non-inferiority")
    adj = holm({k: v["p"] for k, v in h.items()})
    for k, v in h.items():
        lo, hi, _ = boot(v["effect"])
        v.update(mean=sum(v["effect"]) / n, lo=lo, hi=hi, p_holm=adj[k])
        if k == "H4":
            v["verdict"] = "HOLDS" if lo > -MARGIN and adj[k] < ALPHA else "FAILS" if hi < -MARGIN else "NOT SHOWN"
        else:
            v["verdict"] = ("HOLDS" if adj[k] < ALPHA and v["right_way"] else
                            "FAILS" if -MARGIN < lo and hi < MARGIN else "NOT SHOWN")
        del v["effect"]
    return h


def show(title, h, n):
    print(f"== {title}, n={n}")
    for k, v in h.items():
        print(f"{k} {v['verdict']:9s} effect {100 * v['mean']:+.1f} pts, 90% [{100 * v['lo']:+.1f}, {100 * v['hi']:+.1f}], "
              f"p {v['p']:.4f}, Holm {v['p_holm']:.4f} ({v['note']})")


def main(argv):
    pilot = "--pilot" in argv
    prefix = "paper_pilot_t0" if pilot else argv[argv.index("--prefix") + 1] if "--prefix" in argv else "paper_full"
    rows, gold = ledger_rows(prefix), gold_files()
    sets = [set(rows.get(f"{prefix}_{n}", {})) for n in NAMES]
    tasks = sorted(set.intersection(*sets))
    aborted = 0
    prim, sens, tok = {}, {}, {}
    for n in NAMES:
        prim[n], sens[n], tok[n] = [], [], []
        for t in tasks:
            row, first, _ = pick(rows, prefix, n, t)
            prim[n].append(recall(row, gold))
            sens[n].append(0 if rerun_reason(first) else recall(first, gold))
            tok[n].append(tokens(row or first))
            aborted += bool(rerun_reason(first))
    print(f"tasks complete in all five arms {len(tasks)}, in any arm {len(set.union(*sets))}, first-try aborts {aborted}")
    print("gold-file edits:", {n: sum(v) for n, v in prim.items()})
    print("resolved:", {n: sum(bool((pick(rows, prefix, n, t)[0] or {}).get("resolved")) for t in tasks) for n in NAMES})
    if pilot or len(tasks) < 5:
        return
    tf_dir = ROOT / "runs" / prefix / "tf"
    tf_tokens = {}
    for t in tasks:
        f = tf_dir / f"{t}.jsonl.usage.jsonl"
        if f.exists():
            tf_tokens[t] = sum(json.loads(x)["usage"].get("total_tokens", 0) for x in open(f))
    tok["ar_tf"] = [x + tf_tokens.get(t, 0) for x, t in zip(tok["ar_tf"], tasks)]
    main_h, sens_h = analyse(prim), analyse(sens)
    show("Primary", main_h, len(tasks))
    show("Sensitivity (first-try aborts count as 0)", sens_h, len(tasks))
    print(f"H4 tokens: mean AR+anchor {sum(tok['ar_anchor']) / len(tasks):.0f}, AR+TF {sum(tok['ar_tf']) / len(tasks):.0f}, "
          f"Wilcoxon p {wilcoxon(tok['ar_anchor'], tok['ar_tf']):.4f}")
    agree = {}
    for n in ("en", "ar"):
        again = rows.get(f"{prefix}_retest_{n}", {})
        pairs = [(recall(pick(rows, prefix, n, t)[0], gold), recall(r, gold)) for t, r in again.items()]
        agree[n] = f"{sum(a == b for a, b in pairs)}/{len(pairs)}"
    print("retest agreement on gold-file edit:", agree)
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else ROOT / "runs" / prefix / "verdicts.json"
    out.write_text(json.dumps({"n": len(tasks), "primary": main_h, "sensitivity": sens_h, "retest": agree}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
