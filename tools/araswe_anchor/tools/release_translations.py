"""Release format for the translated issues: prose only, code parts replaced by [[C<n>]] placeholders.

The host allowed publishing translations keyed by instance_id, with verbatim parts taken from the original.
So the released file holds the translated prose with every code part masked; the code comes back from the
competition's own tasks.jsonl, using the same mask() as translate_issues.py.

  build    read <lang>_mix_tasks.jsonl, re-mask the restored translation, check that restoring it gives the
           exact same bytes, write release/<lang>.jsonl (instance_id, lang, text, n_placeholders, sha256).
  restore  read release/<lang>.jsonl + tasks.jsonl, rebuild the full translated issues, check every sha256.

Usage:
  python3 release_translations.py build   --src ~/araswe/translations --out results/paper/translations
  python3 release_translations.py restore --rel results/paper/translations/ar.jsonl --tasks data/tasks.jsonl --out ar_mix.jsonl
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from translate_issues import mask, restore, PH  # noqa: E402

LANGS = ["ar", "zh", "hi", "ru", "es", "fr"]
SPLIT = re.compile(r"(\[\[C\d+\]\])")


def sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def remask(translated, parts):
    """Put placeholders back into a restored translation. Longest parts first, never inside a placeholder.
    Equal parts are interchangeable, so any of their indices can take any of their places."""
    free = {}
    for i, p in enumerate(parts):
        free.setdefault(p, []).append(i)
    out = translated
    for p in sorted(free, key=len, reverse=True):
        idx = list(free[p])
        segs = SPLIT.split(out)
        new = []
        for s in segs:
            if s.startswith("[[C") or not idx:
                new.append(s)
                continue
            pieces = s.split(p)
            buf = pieces[0]
            for rest in pieces[1:]:
                buf += (PH % idx.pop(0)) if idx else p
                buf += rest
            new.append(buf)
        out = "".join(new)
        if idx:
            return None, "part not found in translation: %r" % p[:60]
    return out, None


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def build(a):
    tasks = {r["instance_id"]: r["problem_statement"] for r in load(os.path.expanduser(a.tasks))}
    os.makedirs(a.out, exist_ok=True)
    for lang in LANGS:
        src = Path(os.path.expanduser(a.src)) / ("%s_mix_tasks.jsonl" % lang)
        ok = bad = 0
        with open(Path(a.out) / ("%s.jsonl" % lang), "w", encoding="utf-8") as fh:
            for r in load(src):
                _, parts = mask(tasks[r["instance_id"]])
                text, err = remask(r["problem_statement"], parts)
                if err is None:
                    back, problems = restore(text, parts)
                    if back != r["problem_statement"] or problems:
                        err = "restore mismatch %s" % problems
                if err:
                    bad += 1
                    print("SKIP %s %s: %s" % (lang, r["instance_id"], err))
                    continue
                ok += 1
                fh.write(json.dumps({"instance_id": r["instance_id"], "lang": lang, "text": text,
                                     "n_placeholders": len(parts), "sha256": sha(r["problem_statement"])},
                                    ensure_ascii=False) + "\n")
        print("%s: %d released, %d skipped" % (lang, ok, bad))


def restore_cmd(a):
    tasks = {r["instance_id"]: r["problem_statement"] for r in load(os.path.expanduser(a.tasks))}
    ok = bad = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in load(a.rel):
            _, parts = mask(tasks[r["instance_id"]])
            text, problems = restore(r["text"], parts)
            if problems or sha(text) != r["sha256"]:
                bad += 1
                print("MISMATCH %s %s" % (r["instance_id"], problems))
                continue
            ok += 1
            fh.write(json.dumps({"instance_id": r["instance_id"], "problem_statement": text}, ensure_ascii=False) + "\n")
    print("restored %d, mismatched %d -> %s" % (ok, bad, a.out))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--src", default="~/araswe/translations")
    b.add_argument("--tasks", default="~/araswe/data/tasks.jsonl")
    b.add_argument("--out", default="results/paper/translations")
    r = sub.add_parser("restore")
    r.add_argument("--rel", required=True)
    r.add_argument("--tasks", default="~/araswe/data/tasks.jsonl")
    r.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.exit(build(a) if a.cmd == "build" else restore_cmd(a))


if __name__ == "__main__":
    main()
