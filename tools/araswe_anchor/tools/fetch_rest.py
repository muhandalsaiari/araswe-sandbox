"""PREREG Part 2 data: SWE-bench test minus Lite, minus psf/requests, in two size strata, each task's package .py files at base_commit.

usage: python3 -I tools/araswe_anchor/tools/fetch_rest.py [--out ~/araswe/sbrest] [--lite ~/araswe/lite]

Small stratum: under 100 .py files in the task snapshot. Large: over 300. Up to 300 tasks per stratum, seed 42. The count is taken
with git ls-tree over the same package folders as fetch_lite.py, so only sampled tasks are extracted. Reuses the bare clones under
<lite>/repos; nothing from them is ever run. Writes <out>/tasks.jsonl, <out>/strata.csv, <out>/pysnaps/<instance_id>/ (the layout
eval_localization.py reads). Issue text stays local.
"""
import csv
import json
import os
import random
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_lite import PKG, git  # noqa: E402

API = ("https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%%2FSWE-bench&config=default&split=test"
       "&offset=%d&length=100")
CAP, SMALL, LARGE, SEED = 300, 100, 300, 42


def all_rows(out):
    p = out / "swebench_test.jsonl"
    if p.exists():
        return [json.loads(x) for x in open(p)]
    rows, off = [], 0
    while True:
        with urllib.request.urlopen(API % off, timeout=120) as r:
            j = json.load(r)
        rows += [x["row"] for x in j["rows"]]
        off += 100
        if off >= j["num_rows_total"]:
            break
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def snapshot(bare, row):
    """(package folder, .py count) at the task's base commit, or (None, None)."""
    pkg = next((p for p in PKG[row["repo"]] if git(bare, "cat-file", "-e", f"{row['base_commit']}:{p}").returncode == 0), None)
    if not pkg:
        return None, None
    names = git(bare, "ls-tree", "-r", "--name-only", row["base_commit"], pkg).stdout.decode(errors="replace").split("\n")
    return pkg, sum(n.endswith(".py") for n in names)


def main(argv):
    out = Path(os.path.expanduser(argv[argv.index("--out") + 1] if "--out" in argv else "~/araswe/sbrest"))
    lite = Path(os.path.expanduser(argv[argv.index("--lite") + 1] if "--lite" in argv else "~/araswe/lite"))
    out.mkdir(parents=True, exist_ok=True)
    rows = all_rows(out)
    lite_ids = {json.loads(x)["instance_id"] for x in open(lite / "tasks.jsonl")}
    rest = [r for r in rows if r["instance_id"] not in lite_ids and r["repo"] != "psf/requests"]
    print("swebench test", len(rows), "lite", len(lite_ids), "rest", len(rest), flush=True)
    sizes, none = {}, []
    for r in rest:
        bare = lite / "repos" / (r["repo"].replace("/", "__") + ".git")
        pkg, n = snapshot(bare, r)
        if pkg is None:
            none.append(r["instance_id"])
        else:
            sizes[r["instance_id"]] = (pkg, n)
    print("no package or commit", len(none), none[:10], flush=True)
    small = sorted(i for i, (_, n) in sizes.items() if n < SMALL)
    large = sorted(i for i, (_, n) in sizes.items() if n > LARGE)
    print("eligible small", len(small), "large", len(large), "middle", len(sizes) - len(small) - len(large), flush=True)
    rng = random.Random(SEED)
    pick = {"small": sorted(rng.sample(small, min(CAP, len(small)))), "large": sorted(rng.sample(large, min(CAP, len(large))))}
    by_id = {r["instance_id"]: r for r in rest}
    with open(out / "tasks.jsonl", "w") as ft, open(out / "strata.csv", "w", newline="") as fs:
        w = csv.writer(fs)
        w.writerow(["instance_id", "repo", "stratum", "py_files"])
        for s, ids in pick.items():
            for i in ids:
                ft.write(json.dumps(by_id[i], ensure_ascii=False) + "\n")
                w.writerow([i, by_id[i]["repo"], s, sizes[i][1]])
    for s, ids in pick.items():
        repos = {}
        for i in ids:
            repos[by_id[i]["repo"]] = repos.get(by_id[i]["repo"], 0) + 1
        print(s, len(ids), repos, flush=True)
    for s, ids in pick.items():
        for i in ids:
            d = out / "pysnaps" / i
            if (d / ".done").exists():
                continue
            d.mkdir(parents=True, exist_ok=True)
            r = by_id[i]
            bare = lite / "repos" / (r["repo"].replace("/", "__") + ".git")
            a = subprocess.Popen(["git", "-C", str(bare), "archive", r["base_commit"], sizes[i][0]], stdout=subprocess.PIPE)
            subprocess.run(["tar", "-x", "-C", str(d), "--wildcards", "*.py"], stdin=a.stdout, check=True)
            a.wait()
            (d / ".done").write_text("ok")
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
