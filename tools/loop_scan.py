"""Two time sinks seen in traces: the same tool call repeated in a row (a loop) and edit_file calls that fail.

usage: python3 -I tools/loop_scan.py <run_dir> [<run_dir> ...] [--loop N]

Per task-run: the longest streak of identical consecutive tool calls (same tool, same arguments), and how many
edit_file calls failed. A run "loops" when its streak reaches --loop (default 4). Prints the runs that loop or
have 3+ failed edits, then totals split by resolved / unresolved. Reads only.
"""
import collections
import json
import os
import sys


def scan(path):
    steps = json.load(open(path))["steps"]
    best = cur = 0
    prev = None
    edit_fail = edits = 0
    for s in steps:
        content = str((s.get("observation") or {}).get("content", ""))
        for c in s.get("tool_calls") or []:
            key = (c.get("function_name"), json.dumps(c.get("arguments") or {}, sort_keys=True))
            cur = cur + 1 if key == prev else 1
            prev = key
            best = max(best, cur)
            if c.get("function_name") == "edit_file":
                edits += 1
                edit_fail += '"status": "error"' in content
    return best, edits, edit_fail


def main(argv):
    loop = int(argv[argv.index("--loop") + 1]) if "--loop" in argv else 4
    runs = [a for a in argv if os.path.isdir(a)]
    tot = collections.Counter()
    print("%-26s %-22s %-8s %6s %6s %9s" % ("run", "task", "resolved", "streak", "edits", "edit_fail"))
    for d in runs:
        res = {}
        pr = os.path.join(d, "probe_results.jsonl")
        if os.path.exists(pr):
            for line in open(pr):
                r = json.loads(line)
                res[r.get("id")] = bool(r.get("resolved"))
        for f in sorted(os.listdir(os.path.join(d, "traces"))):
            tid = f[len("trace_"):-len(".json")]
            streak, edits, fails = scan(os.path.join(d, "traces", f))
            k = "resolved" if res.get(tid) else "unresolved"
            tot[k] += 1
            tot[k + "_loop"] += streak >= loop
            tot[k + "_fail3"] += fails >= 3
            tot[k + "_edits"] += edits
            tot[k + "_fails"] += fails
            if streak >= loop or fails >= 3:
                print("%-26s %-22s %-8s %6d %6d %9d" % (os.path.basename(d.rstrip("/"))[:26], tid, res.get(tid),
                                                        streak, edits, fails))
    for k in ("resolved", "unresolved"):
        if tot[k]:
            print("%s runs %d: looping (streak >= %d) %d, 3+ failed edits %d, edit_file calls %d of which failed %d"
                  % (k, tot[k], loop, tot[k + "_loop"], tot[k + "_fail3"], tot[k + "_edits"], tot[k + "_fails"]))


if __name__ == "__main__":
    main(sys.argv[1:])
