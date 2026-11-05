"""Fetch SWE-bench Lite for the Exp A replication: tasks.jsonl plus each task's package .py files at base_commit.

usage: python3 -I tools/araswe_anchor/tools/fetch_lite.py [--out ~/araswe/lite]

Writes <out>/tasks.jsonl and <out>/pysnaps/<instance_id>/ with a .done file, the layout eval_localization.py reads with
--data <out> --cache <out>/pysnaps. Repos are bare clones under <out>/repos; nothing from them is ever run.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

API = ("https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%%2FSWE-bench_Lite&config=default&split=test"
       "&offset=%d&length=100")
PKG = {"django/django": ["django"], "sympy/sympy": ["sympy"], "scikit-learn/scikit-learn": ["sklearn"],
       "matplotlib/matplotlib": ["lib/matplotlib"], "pytest-dev/pytest": ["src/_pytest", "_pytest"],
       "sphinx-doc/sphinx": ["sphinx"], "astropy/astropy": ["astropy"], "psf/requests": ["requests"],
       "pydata/xarray": ["xarray"], "pylint-dev/pylint": ["pylint"], "mwaskom/seaborn": ["seaborn"],
       "pallets/flask": ["src/flask", "flask"]}


def tasks(out):
    p = out / "tasks.jsonl"
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


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True)


def main(argv):
    out = Path(os.path.expanduser(argv[argv.index("--out") + 1] if "--out" in argv else "~/araswe/lite"))
    (out / "repos").mkdir(parents=True, exist_ok=True)
    rows = tasks(out)
    print("tasks", len(rows), flush=True)
    bad = 0
    for repo in sorted({r["repo"] for r in rows}):
        bare = out / "repos" / (repo.replace("/", "__") + ".git")
        if not bare.exists():
            subprocess.run(["git", "clone", "--quiet", "--bare", f"https://github.com/{repo}.git", str(bare)], check=True)
        print("cloned", repo, flush=True)
        for r in (x for x in rows if x["repo"] == repo):
            d = out / "pysnaps" / r["instance_id"]
            if (d / ".done").exists():
                continue
            d.mkdir(parents=True, exist_ok=True)
            pkg = next((p for p in PKG[repo] if git(bare, "cat-file", "-e", f"{r['base_commit']}:{p}").returncode == 0), None)
            if not pkg:
                bad += 1
                print("no package", r["instance_id"], flush=True)
                continue
            a = subprocess.Popen(["git", "-C", str(bare), "archive", r["base_commit"], pkg], stdout=subprocess.PIPE)
            subprocess.run(["tar", "-x", "-C", str(d), "--wildcards", "*.py"], stdin=a.stdout, check=True)
            a.wait()
            (d / ".done").write_text("ok")
    print("done, no package for", bad, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
