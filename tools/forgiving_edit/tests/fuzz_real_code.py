"""Stress test of the forgiving edit skill on real code: does it ever change the wrong place?

usage: python3 -I tools/forgiving_edit/tests/fuzz_real_code.py <repo_dir> [<repo_dir> ...] [--n 3000] [--seed 0]

Takes random blocks of 1 to 6 lines from real .py files (tests excluded), damages old_string the ways the 12B
model does, makes new_string = the block with one line changed (damaged the same way), and runs the skill's
find() + syntax guard. Every edit the skill would write is compared with the intended file (the true block
replaced by the true new text):
  right        written, and the file is exactly the intended one
  WRONG        written, and the file is anything else: the failure that must never happen
  refused      not written: ambiguous, not found, or the syntax guard
For the "stale" damage (one word of old_string changed, as when the model misremembers a line) nothing may be
written, and the closest block it prints should cover the true block.
Damages: exact, esc_quotes (\\" for "), esc_squote (\\' for '), bs_newline (a backslash before every line
break), literal_n (lines joined with a typed backslash-n), mixed (esc_quotes + literal_n), json2 (the whole
string JSON-escaped twice by json.dumps, outer quotes dropped), blank_drop (blank lines removed), stale.
"""
import collections
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "edit", "scripts"))
import edit  # noqa: E402

SKIP = {"tests", "test", "docs", "docs_src", ".git", "build", "dist"}


def py_files(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def damage(block, how, rng):
    if how == "exact":
        return block
    if how == "esc_quotes":
        return block.replace('"', '\\"')
    if how == "esc_squote":
        return block.replace("'", "\\'")
    if how == "bs_newline":
        return block.replace("\n", "\\\n")
    if how == "literal_n":
        return block.replace("\n", "\\n")
    if how == "mixed":
        return block.replace('"', '\\"').replace("\n", "\\n")
    if how == "json2":
        return json.dumps(json.dumps(block)[1:-1])[1:-1]
    if how == "json2_bs":   # double JSON escaping, and a stray backslash left before each real line break
        return json.dumps(json.dumps(block)[1:-1])[1:-1].replace("\\\\n", "\\\n")
    if how == "blank_drop":
        return "\n".join(x for x in block.split("\n") if x.strip())
    raise ValueError(how)


def stale(block, rng):
    words = [m for m in re.finditer(r"[A-Za-z_]\w{3,}", block)]
    if not words:
        return None
    m = rng.choice(words)
    return block[:m.start()] + m.group(0) + "_x" + block[m.end():]


def main(argv):
    n, seed, roots, i = 3000, 0, [], 0
    while i < len(argv):
        if argv[i] == "--n":
            n, i = int(argv[i + 1]), i + 2
        elif argv[i] == "--seed":
            seed, i = int(argv[i + 1]), i + 2
        else:
            roots.append(argv[i]); i += 1
    rng = random.Random(seed)
    files = [p for r in roots for p in py_files(r)]
    texts = {}
    for p in files:
        try:
            t = open(p, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        if t.count("\n") >= 10 and edit.compiles(t, p)[0]:
            texts[p] = t
    paths = sorted(texts)
    hows = ["exact", "esc_quotes", "esc_squote", "bs_newline", "literal_n", "mixed", "json2", "json2_bs", "blank_drop", "stale"]
    res = collections.defaultdict(collections.Counter)
    wrong, slow = [], 0.0
    for k in range(n):
        p = rng.choice(paths)
        text = texts[p]
        lines = text.split("\n")
        size = rng.randint(1, 6)
        s = rng.randrange(0, max(len(lines) - size, 1))
        blk_lines = lines[s:s + size]
        while blk_lines and not blk_lines[0].strip():   # start and end on a code line
            blk_lines.pop(0); s += 1
        while blk_lines and not blk_lines[-1].strip():
            blk_lines.pop()
        if not blk_lines:
            continue
        size = len(blk_lines)
        block = "\n".join(blk_lines)
        # change one non-blank line: append a comment (always valid Python unless inside a string or after \)
        nb = [j for j, x in enumerate(blk_lines) if x.strip()]
        j = rng.choice(nb)
        new_lines = list(blk_lines)
        new_lines[j] = new_lines[j] + "  # fz"
        new_block = "\n".join(new_lines)
        how = hows[k % len(hows)]
        if how == "stale":
            old = stale(block, rng)
            if old is None:
                continue
            new = new_block
        else:
            old, new = damage(block, how, rng), damage(new_block, how, rng)
        t0 = time.time()
        got_how, out, places = edit.find(text, old, new)
        if out is not None and not (edit.compiles(text, p)[0] and not edit.compiles(out, p)[0]):
            # the skill would write `out`; the intended file replaces the true block at line s
            intended = {"\n".join(lines[:s] + new_lines + lines[s + size:])}
            if how == "blank_drop":   # blank lines inside the block go with it (the model never sent them)
                intended.add("\n".join(lines[:s] + [x for x in new_lines if x.strip()] + lines[s + size:]))
            if out in intended:
                res[how]["right"] += 1
            else:
                res[how]["WRONG"] += 1
                if len(wrong) < 6:
                    wrong.append((how, p, s + 1, old[:300], got_how))
        elif out is not None:
            res[how]["refused_syntax"] += 1
        elif places:
            res[how]["refused_ambiguous"] += 1
        else:
            res[how]["refused_not_found"] += 1
            first, blk, score = edit.closest_block(old, text)
            covers = first <= s + 1 and first + len(blk) - 1 >= s + size
            res[how]["closest_covers" if covers else "closest_elsewhere"] += 1
        slow = max(slow, time.time() - t0)
    print("files %d, cases %d, seed %d, slowest find %.2fs" % (len(paths), sum(sum(c.values()) for c in res.values()), seed, slow))
    for how in hows:
        c = res[how]
        print("  %-11s %s" % (how, dict(sorted(c.items()))))
    print("WRONG total: %d" % sum(c["WRONG"] for c in res.values()))
    for how, p, ln, o, gh in wrong:
        print("\nWRONG %s %s:%d (matched as %s)\n  old: %r" % (how, p, ln, gh, o))


if __name__ == "__main__":
    main(sys.argv[1:])
