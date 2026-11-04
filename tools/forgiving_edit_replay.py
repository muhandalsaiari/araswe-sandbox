"""Would a forgiving edit_file have rescued the failed edits? Offline replay, no model, no sandbox.

usage: python3 -I tools/forgiving_edit_replay.py <run_dir> [<run_dir> ...] [--snapshots data/snapshots] [--skip run/task ...]

For every trace, rebuild each touched file from the task snapshot (data/snapshots/<task>.tgz) and
replay the trace's own edit_file / write_file calls in order. Successful edits are applied as an exact
unique replace; if one no longer matches the rebuilt file, that file has drifted (e.g. changed by a
run_command) and its later edits are counted as "unknown", never as rescued. For every FAILED edit
the forgiving rule is tried against the file as it stood at that moment:

  0 as-is        old_string unchanged (should never match: the real tool already said no)
  1 quotes       \\" -> "  and  \\' -> '
  2 + bs_newline also drop a backslash right before a line break
  3 + literal_n  also turn a two-character backslash-n into a real line break (and \\t into a tab)
  4 blank_lines  rule (a): the cleaned non-blank lines appear in the file in order as one run, blank
                 lines and trailing spaces ignored; the run is replaced by the cleaned new_string

Each step is cumulative and applied to old_string and new_string alike. An edit is RESCUED at the
first step whose cleaned old_string occurs exactly once in the file; AMBIGUOUS if it occurs more than
once; otherwise NOT RESCUED. The rescued edit is applied, so later edits see the file the forgiving
tool would have produced. Reads only.
"""
import collections
import difflib
import json
import os
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edit_fail_kinds import is_error, kind  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "forgiving_edit", "skills", "edit", "scripts"))
import edit as skill  # noqa: E402  the skill's own matching code, so this replay measures exactly what it does

clean, line_runs, STEPS = skill.clean, skill.line_runs, skill.STEPS
SHOW = 0   # --show-near N: print N near misses (closest block similarity >= 0.9) line by line


def closeness(o, text):
    """Why a fully cleaned old_string still does not match: compare line by line with the file.
    ws_trailing  matches once trailing spaces are ignored on every line
    ws_indent    matches once all leading/trailing spaces are ignored
    lines_all    every line exists in the file, but not as one block (wrong order, gaps, stale)
    lines_most   >= half the lines exist in the file
    lines_few    < half: text the file does not have (invented, or from another file)"""
    def norm(s, f):
        return "\n".join(f(x) for x in s.split("\n"))
    if norm(text, str.rstrip).count(norm(o, str.rstrip)) == 1:
        return "ws_trailing"
    if norm(text, str.strip).count(norm(o, str.strip)) == 1:
        return "ws_indent"
    have = {x.strip() for x in text.split("\n")}
    lines = [x.strip() for x in o.split("\n") if x.strip()]
    hit = sum(x in have for x in lines) / max(len(lines), 1)
    return "lines_all" if hit == 1 else "lines_most" if hit >= 0.5 else "lines_few"


class Snapshot:
    def __init__(self, path):
        self.tf = tarfile.open(path) if os.path.exists(path) else None
        self.names = {}
        if self.tf:
            for m in self.tf.getmembers():
                if m.isfile():
                    self.names[m.name.lstrip("./")] = m

    def read(self, filepath):
        fp = filepath.lstrip("./")
        m = self.names.get(fp) or next((v for k, v in self.names.items() if k.endswith("/" + fp)), None)
        if m is None:
            return None
        return self.tf.extractfile(m).read().decode("utf-8", "replace")


def replay(trace_path, snap, out, examples, tag, near):
    files, drifted = {}, set()
    for s in json.load(open(trace_path))["steps"]:
        content = str((s.get("observation") or {}).get("content", ""))
        failed = is_error(content)
        for c in s.get("tool_calls") or []:
            name, a = c.get("function_name"), c.get("arguments") or {}
            fp = a.get("filepath")
            if name not in ("edit_file", "write_file") or not fp:
                continue
            if name == "write_file":
                if not failed:
                    files[fp] = a.get("content") or ""
                    drifted.discard(fp)
                continue
            if fp not in files and fp not in drifted:
                text = snap.read(fp)
                if text is None:
                    drifted.add(fp)
                else:
                    files[fp] = text
            old, new = a.get("old_string") or "", a.get("new_string") or ""
            k = kind(old)
            if not failed:
                if fp in files and old and files[fp].count(old) >= 1:
                    files[fp] = files[fp].replace(old, new, -1 if a.get("allow_multiple") else 1)
                else:
                    files.pop(fp, None)
                    drifted.add(fp)
                continue
            out["failed"][k] += 1
            if not old:
                out["no_old_string"][k] += 1
                continue
            if fp in drifted or fp not in files:
                out["unknown"][k] += 1
                continue
            text = files[fp]
            if text.count(old) == 1:
                verdict = "as_is_matches"   # the real tool said no; flag, should not happen
            else:
                how, after, places = skill.find(text, old, new)
                verdict = None
                if after is not None:
                    ok_before = not fp.endswith(".py") or skill.compiles(text, fp)[0]
                    if ok_before and fp.endswith(".py") and not skill.compiles(after, fp)[0]:
                        verdict = "refused_syntax"
                    else:
                        verdict = "rescued_" + how
                        files[fp] = after
                elif places:
                    verdict = "ambiguous"
            verdict = verdict or "not_rescued"
            out[verdict][k] += 1
            if verdict == "not_rescued":
                o = clean(old, len(STEPS))
                out["why_not"][closeness(o, text)] += 1
                g = len(line_runs(o, text, gap=3))
                out["with_gaps"]["unique" if g == 1 else "several" if g > 1 else "none"] += 1
                first, block, sc = skill.closest_block(old, text)   # what rule (b) would show the model
                if sc >= 0.9 and len(near) < SHOW:
                    near.append((tag, fp, old, block))
                out["closest_score"][">=0.9" if sc >= 0.9 else "0.7-0.9" if sc >= 0.7 else "<0.7"] += 1
                if len(examples) < 3:
                    examples.append((tag, fp, old[:200]))


def main(argv):
    snaps, skip, dirs, i = "data/snapshots", set(), [], 0
    while i < len(argv):
        if argv[i] == "--snapshots":
            snaps, i = argv[i + 1], i + 2
        elif argv[i] == "--show-near":
            global SHOW
            SHOW, i = int(argv[i + 1]), i + 2
        elif argv[i] == "--skip":
            skip.add(argv[i + 1]); i += 2
        else:
            dirs.append(argv[i]); i += 1
    out = collections.defaultdict(collections.Counter)
    examples, missing_snap, near = [], set(), []
    for d in dirs:
        tdir = os.path.join(d, "traces")
        for f in sorted(os.listdir(tdir)):
            task = f[len("trace_"):-len(".json")]
            tag = os.path.basename(d.rstrip("/")) + "/" + task
            if tag in skip:
                continue
            sp = os.path.join(snaps, task + ".tgz")
            if not os.path.exists(sp):
                missing_snap.add(task)
            replay(os.path.join(tdir, f), Snapshot(sp), out, examples, tag, near)
    total = sum(out["failed"].values())
    print("failed edit_file calls: %d  (by kind: %s)" % (total, dict(out["failed"])))
    order = ["rescued_quotes", "rescued_bs_newline", "rescued_literal_n", "rescued_blank_lines", "refused_syntax", "ambiguous", "not_rescued",
             "unknown", "no_old_string", "as_is_matches"]
    for v in order:
        n = sum(out[v].values())
        if n:
            print("  %-20s %4d (%3.0f%%)  %s" % (v, n, 100 * n / max(total, 1), dict(out[v])))
    rescued = sum(sum(out[v].values()) for v in order[:4])
    judged = total - sum(out["unknown"].values()) - sum(out["no_old_string"].values())
    print("rescued %d of %d judged failed edits (%.0f%%); unknown = file drifted or not in snapshot"
          % (rescued, judged, 100 * rescued / max(judged, 1)))
    if out["why_not"]:
        print("not rescued, closest reason:", dict(out["why_not"].most_common()))
        print("not rescued, in-order match allowing up to 3 skipped code lines (diagnostic, not applied):",
              dict(out["with_gaps"]))
        print("not rescued, similarity of the closest block the skill would show (1.0 = identical):",
              dict(out["closest_score"]))
    if missing_snap:
        print("no snapshot for:", " ".join(sorted(missing_snap)))
    for tag, fp, o, block in near:
        print("\nNEAR MISS %s %s  (- model's old_string after cleaning, + closest file lines; only differing lines)" % (tag, fp))
        want = clean(o, len(STEPS) - 1).split("\n")   # cleaned, so typed \n and stray backslashes are not counted as differences
        for d in difflib.ndiff([x.strip() for x in want], [x.strip() for x in block]):
            if d[:1] in "-+":
                print("  " + d[:2] + repr(d[2:])[:160])
    for tag, fp, o in examples:
        print("\nNOT RESCUED %s %s\n  old_string: %r" % (tag, fp, o))


if __name__ == "__main__":
    main(sys.argv[1:])
