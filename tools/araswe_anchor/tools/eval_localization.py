#!/usr/bin/env python3
"""Experiment A: which localization signals survive translation?

Scores model-free file rankers on the public tasks, at each task's exact base
commit, for one issue-text variant (English by default, or a translated tasks
file with the same instance_ids).

Rankers
  rarest_grep, vote, idf_vote, findfile_*   re-implemented from the public
      notebook "LocBench + findfile: Find the File First" (nobanks, Kaggle,
      Apache-2.0). Kept identical so its English numbers can be reproduced.
  bm25        BM25 over package files (k1=1.5, b=0.75), unicode word tokens,
              identifiers also split on _ and camel humps.
  anchor      skills/anchor/scripts/anchor.py (identifiers only, language-agnostic).

Usage
  python3 eval_localization.py --data ~/araswe/data --cache ~/araswe/cache/pysnaps \
      [--variant translations/ar.jsonl --label ar] [--out results/expA] [--reproduce]

Outputs: a table on stdout, <out>/<label>_per_task.csv (rank of the best gold
file per task and ranker, empty = miss) and <out>/<label>_summary.csv with 95%
bootstrap intervals.
"""
import argparse
import csv
import json
import math
import os
import random
import re
import sys
import tarfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "anchor" / "scripts"))
import anchor  # noqa: E402

PKG = {"fastapi/fastapi": "fastapi", "psf/requests": "src/requests",
       "Textualize/rich": "rich", "encode/httpx": "httpx"}

# Published English numbers from the findfile notebook (125 tasks scored, 4 skipped).
PUBLISHED = {
    "rarest_grep": (0.32, 0.44, 0.50, 0.53, 0.28),
    "vote": (0.31, 0.49, 0.54, 0.57, 0.20),
    "idf_vote": (0.34, 0.50, 0.54, 0.58, 0.20),
    "findfile_tuned": (0.46, 0.74, 0.80, 0.88, 0.02),
    "findfile_generic": (0.40, 0.72, 0.82, 0.90, 0.01),
    "findfile_nolist": (0.39, 0.72, 0.82, 0.90, 0.01),
    "findfile_ids_only": (0.36, 0.53, 0.56, 0.59, 0.20),
}

# ---------------------------------------------------------------- snapshots

def extract_py(tgz, dest, pkg):
    """Keep only the package's .py files (same rule as the findfile notebook)."""
    with tarfile.open(tgz) as tf:
        for m in tf:
            name = m.name.lstrip("./")
            if not m.isfile() or not name.endswith(".py") or ".." in Path(name).parts:
                continue
            if not (name.startswith(pkg + "/") or name.split("/", 1)[-1].startswith(pkg + "/")):
                continue
            t = dest / name
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(tf.extractfile(m).read())


def load_files(d):
    return dict((p.relative_to(d).as_posix(), p.read_text(encoding="utf-8", errors="ignore"))
                for p in sorted(d.rglob("*.py")))

# ---------------------------------------------------- findfile re-implementation

STOP = {"error", "request", "response", "value", "return", "function", "class", "method",
        "python", "import", "should", "would", "could", "example", "issue", "using", "there",
        "which", "where", "when", "this", "that", "with", "from", "none", "true", "false",
        "self", "print", "type", "string", "data", "file", "code", "test", "tests", "default"}

COMMON_WORDS = {
    "about", "after", "again", "because", "being", "before", "could", "doesn", "example",
    "expected", "following", "happen", "instead", "itself", "other", "should", "since",
    "something", "still", "their", "there", "these", "thing", "think", "those", "using",
    "where", "which", "while", "would", "value", "error", "issue", "python", "version",
    "return", "returns", "works", "added", "adding", "currently", "behavior", "behaviour",
    "possible", "request", "response", "default", "function", "method", "class", "import",
    "print", "string", "without", "within", "already", "allow", "allows", "support",
    "supported", "make", "makes", "given", "option", "options", "feature"}

GENERIC = {
    "about", "above", "after", "again", "against", "aren't", "because", "before", "being",
    "below", "between", "both", "cannot", "could", "couldn", "didn", "doesn", "doing", "during",
    "each", "few", "further", "hadn", "hasn", "haven", "having", "herself", "himself", "isn",
    "itself", "mightn", "mustn", "myself", "needn", "other", "ought", "ourselves", "shan",
    "should", "shouldn", "their", "theirs", "them", "themselves", "there", "these", "they",
    "those", "through", "under", "until", "wasn", "weren", "where", "which", "while", "whom",
    "would", "wouldn", "yourself", "yourselves", "please", "thanks", "really", "think"}


def extract_terms(text, k=6):
    cands = []
    cands += re.findall(r"`([^`\n]{3,40})`", text)
    cands += re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b", text)
    cands += re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b", text)
    cands += re.findall(r"\b[a-z_]+\.[a-z_]+(?:\.[a-z_]+)*\b", text)
    seen, out = set(), []
    for c in cands:
        c = c.strip().strip("()")
        if "." in c and " " not in c:
            c = c.split("(")[0].split(".")[-1]
        if len(c) < 3 or c.lower() in STOP or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out[:k]


def pick(text, stop, max_terms=10):
    terms = extract_terms(text)
    for w in re.findall(r"\b[a-z]{5,}\b", text.lower()):
        if w not in stop and w not in terms and len(terms) < max_terms:
            terms.append(w)
    return terms


def findfile_rank(files, terms):
    """Same scoring as the notebook's FINDFILE script, over a rel_path -> text dict."""
    items = sorted(files.items())
    idf = dict((t, math.log((len(items) + 1) / (sum(1 for q, s in items if t in s) + 0.5))) for t in terms)
    out = []
    for p, s in items:
        base = p.split("/")[-1].lower()
        v = sum(idf[t] for t in terms if t in s) + sum(2 * idf[t] for t in terms if t.lower() in base)
        if v > 0:
            out.append((round(v, 1), p))
    return [p for v, p in sorted(out, key=lambda x: (-x[0], x[1]))]


def baseline_rank(files, terms, mode):
    n = len(files)
    df = dict((t, sum(t in s for s in files.values())) for t in terms)
    idf = dict((t, math.log((n + 1) / (df[t] + 0.5))) for t in terms)

    def score(src):
        hit = [t for t in terms if t in src]
        if mode == "vote":
            return len(hit)
        if mode == "idf_vote":
            return sum(idf[t] for t in hit)
        rare = min(terms, key=lambda t: (df[t] == 0, df[t]))
        return 1 if rare in src else 0
    scored = sorted(((score(s), f) for f, s in files.items()), key=lambda x: (-x[0], x[1]))
    return [f for v, f in scored if v > 0]

# --------------------------------------------------------------------- BM25

WORD_RE = re.compile(r"\w+")


def bm25_tokens(text):
    out = []
    for w in WORD_RE.findall(text):
        out.append(w.lower())
        parts = [p for p in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", w) if p]
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
    return out


class BM25:
    def __init__(self, files, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = dict((p, Counter(bm25_tokens(s))) for p, s in files.items())
        self.len = dict((p, sum(c.values())) for p, c in self.docs.items())
        self.avg = sum(self.len.values()) / max(len(self.len), 1)
        self.df = Counter()
        for c in self.docs.values():
            self.df.update(c.keys())
        self.n = len(self.docs)

    def rank(self, query):
        q = set(bm25_tokens(query))
        scores = []
        for p, c in self.docs.items():
            s = 0.0
            for t in q:
                f = c.get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[p] / self.avg))
            if s > 0:
                scores.append((s, p))
        return [p for s, p in sorted(scores, key=lambda x: (-x[0], x[1]))]

# ------------------------------------------------------------------ metrics

def best_rank(ranked, gold):
    return min((ranked.index(g) + 1 for g in gold if g in ranked), default=None)


def summary(ranks):
    n = len(ranks)
    vals = [sum(1 for x in ranks if x and x <= k) / n for k in (1, 3, 5, 10)]
    vals.append(sum(1 for x in ranks if not x) / n)
    vals.append(sum(1.0 / x for x in ranks if x) / n)  # MRR
    return vals


def bootstrap_top3(ranks, reps=10000, seed=0):
    rng = random.Random(seed)
    n = len(ranks)
    hits = [1 if (x and x <= 3) else 0 for x in ranks]
    stats = sorted(sum(hits[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return stats[int(0.025 * reps)], stats[int(0.975 * reps) - 1]

# --------------------------------------------------------------------- main

RANKERS = ["rarest_grep", "vote", "idf_vote", "findfile_tuned", "findfile_generic",
           "findfile_nolist", "findfile_ids_only", "bm25", "anchor"]


def run(args):
    data = Path(args.data).expanduser()
    cache = Path(args.cache).expanduser()
    rows = [json.loads(l) for l in open(data / "tasks.jsonl", encoding="utf-8") if l.strip()]
    texts = dict((r["instance_id"], r["problem_statement"]) for r in rows)
    if args.variant:
        var = [json.loads(l) for l in open(Path(args.variant).expanduser(), encoding="utf-8") if l.strip()]
        vmap = dict((v["instance_id"], v["problem_statement"]) for v in var)
        missing = [i for i in texts if i not in vmap]
        if missing:
            print("WARNING: %d tasks missing from variant, using English for them: %s" % (len(missing), missing[:5]))
        texts.update(vmap)
    if args.only:
        rows = [r for r in rows if r["instance_id"] in set(args.only.split(","))]

    res = dict((m, []) for m in RANKERS)
    ids, repos, blind, skipped = [], [], [], 0
    for i, r in enumerate(rows):
        d = cache / r["instance_id"]
        if not (d / ".done").exists():
            d.mkdir(parents=True, exist_ok=True)
            extract_py(data / "snapshots" / ("%s.tgz" % r["instance_id"]), d, PKG[r["repo"]])
            (d / ".done").write_text("ok")
        files = load_files(d)
        gold = [f for f in re.findall(r"^\+\+\+ b/(\S+)", r["patch"], re.M) if f in files]
        if not gold:
            skipped += 1
            continue
        text = texts[r["instance_id"]]
        ids.append(r["instance_id"])
        repos.append(r["repo"])
        idents = extract_terms(text)
        for m in ("rarest_grep", "vote", "idf_vote"):
            res[m].append(best_rank(baseline_rank(files, idents, m), gold) if idents else None)
        for m, fn in (("findfile_tuned", lambda t: pick(t, COMMON_WORDS)),
                      ("findfile_generic", lambda t: pick(t, GENERIC)),
                      ("findfile_nolist", lambda t: pick(t, set())),
                      ("findfile_ids_only", extract_terms)):
            terms = fn(text)
            res[m].append(best_rank(findfile_rank(files, terms), gold) if terms else None)
        res["bm25"].append(best_rank(BM25(files).rank(text), gold))
        a = anchor.analyze(text, files=files)
        res["anchor"].append(best_rank([p for _s, p in a["files"]], gold))
        blind.append(a["blind"])
        if args.verbose and i % 20 == 0:
            print("%d/%d" % (i + 1, len(rows)), file=sys.stderr)

    n = len(ids)
    label = args.label
    print("Experiment A  variant=%s  %d tasks scored, %d skipped, anchor-blind %d (%.0f%%)\n"
          % (label, n, skipped, sum(blind), 100.0 * sum(blind) / max(n, 1)))
    print("%-20s%7s%7s%7s%7s%7s%7s   top3 95%% CI" % ("ranker", "top1", "top3", "top5", "top10", "miss", "MRR"))
    summ = {}
    for m in RANKERS:
        s = summary(res[m])
        lo, hi = bootstrap_top3(res[m])
        summ[m] = s + [lo, hi]
        print("%-20s" % m + "".join("%7.0f%%" % (100 * v) if j < 5 else "%7.2f" % v for j, v in enumerate(s))
              + "   [%.0f%%, %.0f%%]" % (100 * lo, 100 * hi))

    if args.reproduce:
        print("\nReproduction gate (English only): ours vs published, top1/top3/top5/top10/miss")
        ok = True
        for m, pub in PUBLISHED.items():
            ours = summ[m][:5]
            diff = max(abs(a - b) for a, b in zip(ours, pub))
            flag = "OK" if diff <= 0.015 else "MISMATCH"
            ok = ok and flag == "OK"
            print("  %-18s ours %s  published %s  max diff %.1f pts  %s" % (
                m, "/".join("%.0f" % (100 * v) for v in ours), "/".join("%.0f" % (100 * v) for v in pub),
                100 * diff, flag))
        print("GATE:", "PASS" if ok else "FAIL (fix the pipeline before trusting other numbers)")

    print("\nTop-3 by repo:")
    for repo in sorted(set(repos)):
        idx = [i for i, x in enumerate(repos) if x == repo]
        print("  %-18s n=%-3d " % (repo, len(idx)) + "  ".join(
            "%s %.0f%%" % (m, 100.0 * sum(1 for i in idx if res[m][i] and res[m][i] <= 3) / len(idx))
            for m in ("idf_vote", "findfile_nolist", "findfile_ids_only", "anchor")))

    if args.out:
        out = Path(args.out).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        with open(out / ("%s_per_task.csv" % label), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["instance_id", "repo", "anchor_blind"] + RANKERS)
            for i, tid in enumerate(ids):
                w.writerow([tid, repos[i], int(blind[i])] + [res[m][i] or "" for m in RANKERS])
        with open(out / ("%s_summary.csv" % label), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ranker", "top1", "top3", "top5", "top10", "miss", "mrr", "top3_lo", "top3_hi"])
            for m in RANKERS:
                w.writerow([m] + ["%.4f" % v for v in summ[m]])
        print("\nwrote %s" % out)
    return summ


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="~/araswe/data", help="folder with tasks.jsonl and snapshots/")
    ap.add_argument("--cache", default="~/araswe/cache/pysnaps", help="where package .py files are extracted")
    ap.add_argument("--variant", help="tasks file with translated problem_statement, same instance_ids")
    ap.add_argument("--label", default="en")
    ap.add_argument("--out", help="folder for CSV outputs")
    ap.add_argument("--only", help="comma-separated instance_ids (debugging)")
    ap.add_argument("--reproduce", action="store_true", help="compare with the published findfile numbers")
    ap.add_argument("--verbose", action="store_true")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
