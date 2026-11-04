---
name: anchor
description: Finds where in the repository the issue points, before any searching. Pulls code identifiers, file paths and traceback frames out of the issue text (in any language) and resolves them to definitions as path:line. Deterministic, no model call, about one second.
---

# anchor

Use this FIRST, before grep, read_file or any other search.

## How to run

Run the script scripts/anchor.py of this skill and pass it the full issue text exactly as you received it: all of it, in its original language, including code blocks and tracebacks. Do not summarize or translate it.

## What it prints

- ANCHORS: lines of the form symbol -> path:line, most specific first. Each line says where the evidence came from (traceback frame, file named in issue, code span, dotted name, code block, identifier).
- FILES: the files most likely to need the change, best first.
- NO_ANCHOR: the issue names no code that exists in this repository.

## What to do with it

1. Read the definition at the first ANCHOR line (read_file starting a few lines before that line).
2. If the fix is not there, check the next two anchors before searching anywhere else.
3. Then use get_code_neighbors on the best symbol to see its callers and callees.
4. If it printed NO_ANCHOR, use your normal search.

The ranking is a strong hint, not a guarantee: the file to change is usually among the first three FILES, not always the first.
