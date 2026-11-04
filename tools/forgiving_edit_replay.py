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

Each step is cumulative and applied to old_string and new_string alike. An edit is RESCUED at the
first step whose cleaned old_string occurs exactly once in the file; AMBIGUOUS if it occurs more than
once; otherwise NOT RESCUED. The rescued edit is applied, so later edits see the file the forgiving
tool would have produced. Reads only.
"""
import collections
import json
import os
import sys
import tarfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edit_fail_kinds import is_error, kind  # noqa: E402

STEPS = ("quotes", "bs_newline", "literal_n")


def clean(text, upto):
    if upto >= 1:
        text = text.replace('\\"', '"').replace("\\'", "'")
    if upto >= 2:
        text = text.replace("\\\n", "\n")
    if upto >= 3:
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text


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


def replay(trace_path, snap, out, examples, tag):
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
            text, verdict = files[fp], None
            if text.count(old) == 1:
                verdict = "as_is_matches"   # the real tool said no; flag, should not happen
            tried = {old}
            for i, step in enumerate(STEPS, 1):
                if verdict:
                    break
                o = clean(old, i)
                if o in tried:
                    continue
                tried.add(o)
                n = text.count(o)
                if n == 1:
                    verdict = "rescued_" + step
                    files[fp] = text.replace(o, clean(new, i), 1)
                elif n > 1:
                    verdict = "ambiguous"
            verdict = verdict or "not_rescued"
            out[verdict][k] += 1
            if verdict == "not_rescued" and len(examples) < 3:
                examples.append((tag, fp, old[:200]))


def main(argv):
    snaps, skip, dirs, i = "data/snapshots", set(), [], 0
    while i < len(argv):
        if argv[i] == "--snapshots":
            snaps, i = argv[i + 1], i + 2
        elif argv[i] == "--skip":
            skip.add(argv[i + 1]); i += 2
        else:
            dirs.append(argv[i]); i += 1
    out = collections.defaultdict(collections.Counter)
    examples, missing_snap = [], set()
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
            replay(os.path.join(tdir, f), Snapshot(sp), out, examples, tag)
    total = sum(out["failed"].values())
    print("failed edit_file calls: %d  (by kind: %s)" % (total, dict(out["failed"])))
    order = ["rescued_quotes", "rescued_bs_newline", "rescued_literal_n", "ambiguous", "not_rescued",
             "unknown", "no_old_string", "as_is_matches"]
    for v in order:
        n = sum(out[v].values())
        if n:
            print("  %-20s %4d (%3.0f%%)  %s" % (v, n, 100 * n / max(total, 1), dict(out[v])))
    rescued = sum(sum(out[v].values()) for v in order[:3])
    judged = total - sum(out["unknown"].values()) - sum(out["no_old_string"].values())
    print("rescued %d of %d judged failed edits (%.0f%%); unknown = file drifted or not in snapshot"
          % (rescued, judged, 100 * rescued / max(judged, 1)))
    if missing_snap:
        print("no snapshot for:", " ".join(sorted(missing_snap)))
    for tag, fp, o in examples:
        print("\nNOT RESCUED %s %s\n  old_string: %r" % (tag, fp, o))


if __name__ == "__main__":
    main(sys.argv[1:])
