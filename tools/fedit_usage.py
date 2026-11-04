"""Did the forgiving-edit skill get used, and did it help? Reads one or more run folders, no model, no sandbox.

usage: python3 -I tools/fedit_usage.py <run_dir> [<run_dir> ...] [--show N]

Per run: edit_file calls (ok / failed, and the harness's own match strategy on the ok ones), run_skill_script
calls of the edit skill by outcome (the first words of its output: EDITED, NOT EDITED ... matches N places,
NOT EDITED ... is not in, NOT EDITED ... break Python syntax, ERROR, or a tool error), and what followed:
  failed edit -> skill next     how often the model called the skill right after a failed edit_file (the
                                prompt asks it to; anything else is a miss of that instruction)
  NOT EDITED -> landed          after a NOT EDITED on a file, did a later edit_file or skill call on that
                                same file succeed before the run ended
--show N prints the first N skill calls with their output, cut to 600 chars each.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edit_fail_kinds import is_error  # noqa: E402


def outcome(content):
    c = content
    try:  # the tool result is JSON; the script's stdout sits inside it
        j = json.loads(content)
        if isinstance(j, dict):
            c = str(j.get("stdout") or j.get("result") or j.get("output") or j.get("error") or content)
    except (ValueError, TypeError):
        pass
    if "EDITED " in c and "NOT EDITED" not in c:
        return "edited"
    if "NOT EDITED" in c:
        if "matches" in c and "places" in c:
            return "not_edited_ambiguous"
        if "break Python syntax" in c:
            return "not_edited_syntax"
        return "not_edited_not_found"
    if "ERROR:" in c:
        return "script_error"
    if is_error(content):
        return "tool_error"
    return "other"


def scan(trace_path, out, shown, show, tag):
    steps = json.load(open(trace_path))["steps"]
    calls = []  # (name, args, content)
    for s in steps:
        content = str((s.get("observation") or {}).get("content", ""))
        for c in s.get("tool_calls") or []:
            calls.append((c.get("function_name"), c.get("arguments") or {}, content))
    pending = {}  # filepath -> True while a NOT EDITED is unresolved
    for i, (name, a, content) in enumerate(calls):
        if name == "edit_file":
            if is_error(content):
                out["edit_failed"] += 1
                nxt = calls[i + 1][0] if i + 1 < len(calls) else None
                out["failed_edit_next_" + ("skill" if nxt == "run_skill_script" else "edit_file" if nxt == "edit_file"
                                           else "other" if nxt else "end")] += 1
            else:
                out["edit_ok"] += 1
                st = ""
                try:
                    st = json.loads(content).get("strategy", "")
                except (ValueError, TypeError, AttributeError):
                    pass
                out["edit_ok_strategy_" + (st or "?")] += 1
                fp = a.get("filepath")
                if pending.pop(fp, None):
                    out["not_edited_then_landed"] += 1
        elif name == "run_skill_script":
            out["skill_calls"] += 1
            if a.get("skill_name") != "edit":
                out["skill_other_name"] += 1
                continue
            sa = a.get("args")
            fp = sa.get("filepath") if isinstance(sa, dict) else None
            if not isinstance(sa, dict):
                out["skill_args_not_dict"] += 1
            o = outcome(content)
            out["skill_" + o] += 1
            if o == "edited" and pending.pop(fp, None):
                out["not_edited_then_landed"] += 1
            if o.startswith("not_edited"):
                if fp not in pending:
                    out["not_edited_files"] += 1
                pending[fp] = True
            if len(shown) < show:
                shown.append((tag, json.dumps(a, ensure_ascii=False)[:600], content[:600]))


def main(argv):
    show, dirs, i = 0, [], 0
    while i < len(argv):
        if argv[i] == "--show":
            show, i = int(argv[i + 1]), i + 2
        else:
            dirs.append(argv[i]); i += 1
    shown = []
    for d in dirs:
        out = collections.Counter()
        tdir = os.path.join(d, "traces")
        if not os.path.isdir(tdir):
            print("%s: no traces folder (run not started or still empty)" % d)
            continue
        for f in sorted(os.listdir(tdir)):
            scan(os.path.join(tdir, f), out, shown, show, os.path.basename(d.rstrip("/")) + "/" + f[6:-5])
        print(os.path.basename(d.rstrip("/")))
        for k in sorted(out):
            print("  %-34s %d" % (k, out[k]))
    for tag, a, c in shown:
        print("\nSKILL CALL %s\n  args: %s\n  ->   %s" % (tag, a, c))


if __name__ == "__main__":
    main(sys.argv[1:])
