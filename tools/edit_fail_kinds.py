"""Why do edit_file calls fail? Sorts every failed edit_file call by what is odd about its old_string.

usage: python3 -I tools/edit_fail_kinds.py <run_dir> [<run_dir> ...]

Kinds, first match wins:
  missing      old_string absent (the framework rejects the call before it runs)
  esc_quote    old_string holds \\" or \\' : a quote escaped as if inside a JSON string; code rarely has that
  esc_newline  old_string holds a backslash right before a line break
  long         more than 3 lines (the prompt asks for 1 to 3 whole lines)
  other        none of the above (whitespace, invented or stale text: needs the file to tell)
Also prints the same kinds for edit_file calls that succeeded, as the base rate. Reads only.
"""
import collections
import json
import os
import sys


def is_error(content):
    """A tool call failed. Two shapes: the tool's own error ({"status": "error", ...}) and the
    framework rejecting the call before it ran ({"error": "Invoking `edit_file()` failed as the
    following mandatory input parameters are not present: ..."}). Checking only the first counted
    214 rejected edit_file calls as successes (2026-11-04)."""
    return '"status": "error"' in content or content.lstrip().startswith('{"error"')


def kind(old):
    if not old:
        return "missing"
    if '\\"' in old or "\\'" in old:
        return "esc_quote"
    if "\\\n" in old:
        return "esc_newline"
    if old.count("\n") >= 3:
        return "long"
    return "other"


def main(argv):
    fail, ok = collections.Counter(), collections.Counter()
    for d in (a for a in argv if os.path.isdir(a)):
        for f in sorted(os.listdir(os.path.join(d, "traces"))):
            for s in json.load(open(os.path.join(d, "traces", f)))["steps"]:
                content = str((s.get("observation") or {}).get("content", ""))
                for c in s.get("tool_calls") or []:
                    if c.get("function_name") != "edit_file":
                        continue
                    k = kind((c.get("arguments") or {}).get("old_string"))
                    (fail if is_error(content) else ok)[k] += 1
    for name, c in (("failed", fail), ("succeeded", ok)):
        n = sum(c.values())
        print("%s edit_file calls %d: " % (name, n) + ", ".join(
            "%s %d (%.0f%%)" % (k, c[k], 100 * c[k] / max(n, 1)) for k in ("missing", "esc_quote", "esc_newline", "long", "other")))


if __name__ == "__main__":
    main(sys.argv[1:])
