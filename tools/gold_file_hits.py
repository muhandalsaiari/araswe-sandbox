"""Did the agent find the right file? Per task-run: did it open, and did it edit, a file the gold patch changes.

usage: python3 -I tools/gold_file_hits.py <run_dir> [<run_dir> ...] [--tasks ~/araswe/data/tasks.jsonl]

If unresolved runs mostly opened AND edited the right file, a better file finder will not move the score;
the loss is in the fix or the clock. If they mostly never opened it, localization is the lever.
Paths are compared after stripping a leading ./ or /workspace/ or /testbed/. Reads only.
"""
import collections
import json
import os
import re
import sys

PREFIXES = ("./", "/workspace/", "/testbed/", "/repo/")


def norm(p):
    p = (p or "").strip()
    for pre in PREFIXES:
        if p.startswith(pre):
            p = p[len(pre):]
    return p


def main(argv):
    tasks = os.path.expanduser(argv[argv.index("--tasks") + 1] if "--tasks" in argv else "~/araswe/data/tasks.jsonl")
    runs = [a for a in argv if not a.startswith("--") and a != tasks and os.path.isdir(a)]
    gold = {}
    for line in open(tasks):
        r = json.loads(line)
        gold[r["instance_id"]] = {f for f in re.findall(r"^\+\+\+ b/(\S+)", r.get("patch") or "", re.M)
                                  if not f.startswith("tests/")}
    total = collections.Counter()
    stuck = collections.Counter()
    print("%-28s %-24s %-9s %-7s %-7s %s" % ("run", "task", "resolved", "opened", "edited", "gold files"))
    for d in runs:
        res, why = {}, {}
        pr = os.path.join(d, "probe_results.jsonl")
        if os.path.exists(pr):
            for line in open(pr):
                r = json.loads(line)
                res[r.get("id")] = bool(r.get("resolved"))
                why[r.get("id")] = ("clock cut" if r.get("kaggle_cut") else
                                    (r.get("harness_error") or "no error").split(":")[0].split("(")[0].strip()[:45])
        for f in sorted(os.listdir(os.path.join(d, "traces"))):
            tid = f[len("trace_"):-len(".json")]
            g = gold.get(tid) or set()
            steps = json.load(open(os.path.join(d, "traces", f)))["steps"]
            opened = edited = False
            for s in steps:
                failed = '"status": "error"' in str((s.get("observation") or {}).get("content", ""))
                for c in s.get("tool_calls") or []:
                    a = c.get("arguments") or {}
                    name = c.get("function_name")
                    fp = norm(a.get("filepath"))
                    cmd = a.get("command") or ""
                    if name == "read_file" and fp in g or name == "run_command" and any(x in cmd for x in g):
                        opened = True
                    if name in ("edit_file", "write_file") and fp in g and not failed:
                        edited = True
            ok = res.get(tid)
            key = "resolved" if ok else "unresolved"
            total[key] += 1
            total[key + "_opened"] += opened
            total[key + "_edited"] += edited
            if not ok and opened and not edited:
                stuck[why.get(tid, "?")] += 1
            print("%-28s %-24s %-9s %-7s %-7s %s" % (os.path.basename(d.rstrip("/"))[:28], tid, ok, opened, edited,
                                                     " ".join(sorted(g))))
    for k in ("resolved", "unresolved"):
        if total[k]:
            print("%s runs: %d, opened a gold file %d (%.0f%%), edited one %d (%.0f%%)" % (
                k, total[k], total[k + "_opened"], 100 * total[k + "_opened"] / total[k],
                total[k + "_edited"], 100 * total[k + "_edited"] / total[k]))

    if stuck:
        print("unresolved, opened but never edited, by how the run ended: " +
              ", ".join("%s %d" % kv for kv in stuck.most_common()))


if __name__ == "__main__":
    main(sys.argv[1:])
