#!/usr/bin/env python3
"""edit: a forgiving replacement for a failed edit_file call. Standard library only, no model call.

Why: on the English 12B screen_01 runs, 74% of edit_file calls failed (journal 2026-11-04). Most failed
old_strings carry JSON-style escaping the file does not have (\\" for a quote, a backslash before a line
break, backslash-n typed as two characters); many others hold the right lines with blank lines
differing. The model then retries blind, because "old_string not found" does not say what IS there.

What it does, in order, stopping at the first that finds exactly ONE place in the file:
  1 exact          old as given
  2 quotes         \\" -> "  and  \\' -> '
  3 bs_newline     + drop a backslash right before a line break
  4 literal_n      + turn a typed backslash-n into a line break (and backslash-t into a tab)
  5 blank_lines    the cleaned lines appear in the file in order as one run, blank lines and
                   trailing spaces ignored
The same cleaning is applied to new. Then, for a .py file, the result must still compile if the
original did; otherwise nothing is written. If more than one place matches, nothing is written and
the places are listed. If nothing matches, nothing is written and the closest real block of the file
is printed with line numbers, so the next call can copy it exactly.

Usage (inside the sandbox, repository at /workspace), as run_skill_script sends a dict argument:
    python3 edit.py --filepath fastapi/routing.py --old_string "..." --new_string "..."
Options: --root DIR (default: the first of /workspace, $PWD, /testbed, /repo, cwd that holds the file),
--dry_run 1 (report only). Always exits 0; the first word of the output is the outcome.
"""
import collections
import difflib
import os
import re
import sys

WORD = re.compile(r"\w+")

STEPS = ("exact", "quotes", "bs_newline", "literal_n")


def clean(text, upto):
    """Cumulative cleaning; upto is an index into STEPS (0 = unchanged)."""
    if upto >= 1:
        text = text.replace('\\"', '"').replace("\\'", "'")
    if upto >= 2:
        text = text.replace("\\\n", "\n")
    if upto >= 3:
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text


def line_runs(old, text, gap=0):
    """Spans (first, last) of file lines where old's non-blank lines appear in order, trailing spaces
    dropped, blank file lines skipped. gap = NON-blank file lines that may be skipped in total; only
    gap=0 is ever applied (a gap would delete the skipped lines)."""
    want = [x.rstrip() for x in old.split("\n") if x.strip()]
    have = text.split("\n")
    if not want:
        return []
    spans = []
    for i, line in enumerate(have):
        if line.rstrip() != want[0]:
            continue
        j, k, skipped = i + 1, 1, 0
        while k < len(want) and j < len(have):
            h = have[j].rstrip()
            if h == want[k]:
                k += 1
            elif h.strip() and skipped < gap:
                skipped += 1
            elif h.strip():
                break
            j += 1
        if k == len(want):
            spans.append((i, j - 1))
    return spans


def find(text, old, new):
    """Return (how, new_text, places). new_text is None unless exactly one place matched.
    places = 1-based first lines of every match at the first step that matched anything."""
    tried = set()
    for i, how in enumerate(STEPS):
        o = clean(old, i)
        if not o or o in tried:
            continue
        tried.add(o)
        n = text.count(o)
        if n == 1:
            return how, text.replace(o, clean(new, i), 1), [text[:text.index(o)].count("\n") + 1]
        if n > 1:
            places, start = [], 0
            while True:
                p = text.find(o, start)
                if p < 0:
                    break
                places.append(text[:p].count("\n") + 1)
                start = p + 1
            return how, None, places
    o, nw = clean(old, len(STEPS) - 1), clean(new, len(STEPS) - 1)
    spans = line_runs(o, text)
    if len(spans) == 1:
        lines = text.split("\n")
        s, e = spans[0]
        return "blank_lines", "\n".join(lines[:s] + nw.split("\n") + lines[e + 1:]), [s + 1]
    if spans:
        return "blank_lines", None, [s + 1 for s, _ in spans]
    return None, None, []


def closest_block(old, text, pad=2):
    """The file window most like old, as (first_line_1based, lines, score). Windows are ranked by shared
    words (fast), then the best few by character similarity, so stale or half-remembered text still
    lands on the right place."""
    o = clean(old, len(STEPS) - 1)
    want = [x for x in o.split("\n") if x.strip()] or [o]
    have = text.split("\n")
    n = max(len(want), 1)
    owords = collections.Counter(w for x in want for w in WORD.findall(x))
    lwords = [collections.Counter(WORD.findall(x)) for x in have]
    ranked = []
    for i in range(0, max(len(have) - n + 1, 1)):
        win = collections.Counter()
        for c in lwords[i:i + n]:
            win.update(c)
        shared = sum((win & owords).values())
        if shared:
            ranked.append((shared, i))
    ranked.sort(reverse=True)
    best, best_i = 0.0, (ranked[0][1] if ranked else 0)
    target = "\n".join(x.strip() for x in want)
    for _, i in ranked[:8]:
        win = "\n".join(x.strip() for x in have[i:i + n] if x.strip())
        score = difflib.SequenceMatcher(None, target, win, autojunk=False).ratio()
        if score > best:
            best, best_i = score, i
    s = max(best_i - pad, 0)
    return s + 1, have[s:best_i + n + pad], best


def compiles(src, name):
    try:
        compile(src, name, "exec")
        return True, ""
    except SyntaxError as e:
        return False, "line %s: %s" % (e.lineno, e.msg)


def find_root(given, fp):
    """The repository folder. run_skill_script runs this script inside its own temporary folder (it
    chdirs there first), so the current folder is NOT the repository. Take the first candidate that
    holds fp: --root, /workspace, $PWD (chdir does not change it), /testbed, /repo, the current folder."""
    cands = [given] if given else []
    cands += ["/workspace", os.environ.get("PWD"), "/testbed", "/repo", os.getcwd()]
    cands = [c for c in cands if c and os.path.isdir(c)]
    for c in cands:
        if fp and os.path.isfile(fp if os.path.isabs(fp) else os.path.join(c, fp)):
            return c
    return cands[0] if cands else os.getcwd()


def main(argv):
    opts, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]; i += 2
        else:
            i += 1
    fp = (opts.get("filepath") or opts.get("file_path") or opts.get("path") or "").strip()
    root = find_root(opts.get("root"), fp)
    old = opts.get("old_string", opts.get("old"))
    new = opts.get("new_string", opts.get("new", ""))
    if not fp or old is None:
        print("ERROR: needs filepath, old_string and new_string in args.")
        return 2
    path = fp if os.path.isabs(fp) else os.path.join(root, fp)
    if not os.path.isfile(path):
        print("ERROR: no file %s. Check the path with: grep -rln \"<a line you expect>\" --include=\"*.py\" ." % fp)
        return 2
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        text = fh.read()
    if not old.strip():
        print("ERROR: old_string is empty. Copy 1 to 3 whole lines from read_file.")
        return 2
    how, out, places = find(text, old, new)
    if out is None and places:
        print("NOT EDITED: old_string matches %d places (lines %s). Add one more line from around the place "
              "you mean so it matches once." % (len(places), ", ".join(map(str, places[:10]))))
        return 1
    if out is None:
        first, block, score = closest_block(old, text)
        print("NOT EDITED: old_string is not in %s, even after removing stray backslashes. The closest "
              "lines in the file are below (line numbers on the left are not part of the file). Copy "
              "old_string from them exactly." % fp)
        for k, line in enumerate(block):
            print("%5d| %s" % (first + k, line))
        return 1
    if path.endswith(".py"):
        ok_before, _ = compiles(text, fp)
        ok_after, err = compiles(out, fp)
        if ok_before and not ok_after:
            print("NOT EDITED: the change would break Python syntax (%s). Check new_string: real line "
                  "breaks, quotes without backslashes, the same indentation as the lines around it." % err)
            return 1
    if opts.get("dry_run") not in (None, "", "0", "false", "False"):
        print("DRY RUN: would edit %s at line %d (%s)." % (fp, places[0], how))
        return 0
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(out)
    diff = difflib.unified_diff(text.split("\n"), out.split("\n"), "a/" + fp, "b/" + fp, n=1, lineterm="")
    print("EDITED %s at line %d%s." % (fp, places[0], "" if how == "exact" else " (matched after fixing: %s)" % how))
    print("\n".join(list(diff)[:40]))
    return 0


if __name__ == "__main__":
    # Always exit 0: run_skill_script runs this with runpy and re-raises a non-zero SystemExit, which
    # would turn NOT EDITED (and the closest lines it prints) into a tool error. The first word of the
    # output (EDITED / NOT EDITED / ERROR / DRY RUN) carries the outcome instead.
    main(sys.argv[1:])
