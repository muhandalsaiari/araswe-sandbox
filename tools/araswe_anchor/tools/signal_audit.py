"""Signal audit: which parts of an issue carry localization signal? Writes one task variant per ablation for eval_localization.py.

usage: python3 -I tools/araswe_anchor/tools/signal_audit.py <out_dir> [--tasks ~/araswe/data/tasks.jsonl] [--ar ~/araswe/translations/ar_mix_tasks.jsonl]

Every issue is split with translate_issues.mask into prose and code parts. Parts are sorted into block (fenced code), inline
(backticks), trace (traceback lines), url, ident (bare names and paths in prose). A variant drops one class or keeps one class.
ar_latin drops the Arabic letters from AR-MIX: if it scores like AR-MIX, the ranker reads only what stayed in Latin script.
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate_issues import PH_RE, mask  # noqa: E402

CLASSES = ("block", "inline", "trace", "url", "ident")


def kind(p):
    if "Traceback (most recent call last)" in p or re.search(r'^\s*File "', p, re.M):
        return "trace"
    if p.startswith("```") or p.startswith("~~~"):
        return "block"
    if p.startswith("`"):
        return "inline"
    if p.startswith("http") or "://" in p:
        return "url"
    return "ident"


def build(text, keep_prose, keep):
    masked, parts = mask(text)

    def sub(m):
        p = parts[int(m.group(1))]
        return p if kind(p) in keep else " "
    if not keep_prose:
        pieces = re.split(r"(\[\[C\d+\]\])", masked)
        masked = " ".join(x for x in pieces if x.startswith("[[C"))
    return PH_RE.sub(sub, masked)


def main(argv):
    out = argv[0]
    tasks = os.path.expanduser(argv[argv.index("--tasks") + 1] if "--tasks" in argv else "~/araswe/data/tasks.jsonl")
    ar = os.path.expanduser(argv[argv.index("--ar") + 1] if "--ar" in argv else "~/araswe/translations/ar_mix_tasks.jsonl")
    rows = [json.loads(x) for x in open(tasks)]
    variants = {"no_prose": (False, set(CLASSES)), "prose_only": (True, set())}
    for c in CLASSES:
        variants["no_" + c] = (True, set(CLASSES) - {c})
        variants["only_" + c] = (False, {c})
    os.makedirs(out, exist_ok=True)
    counts = collections.Counter()
    for r in rows:
        for p in mask(r["problem_statement"])[1]:
            counts[kind(p)] += 1
    print("parts by class", dict(counts))
    for name, (prose, keep) in variants.items():
        with open(os.path.join(out, name + ".jsonl"), "w") as f:
            for r in rows:
                t = build(r["problem_statement"], prose, keep).strip() or "none"
                f.write(json.dumps({"instance_id": r["instance_id"], "repo": r["repo"], "problem_statement": t}, ensure_ascii=False) + "\n")
    with open(os.path.join(out, "ar_latin.jsonl"), "w") as f:
        for x in open(ar):
            r = json.loads(x)
            t = re.sub(r"[؀-ۿ]+", " ", r["problem_statement"]).strip() or "none"
            f.write(json.dumps({"instance_id": r["instance_id"], "repo": r["repo"], "problem_statement": t}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
