---
name: anchor
description: Finds where in the repository the issue points, before any searching. Give it the code names from the issue (function, class and variable names, dotted names, file paths) and it resolves them to definitions as path:line. Deterministic, no model call, about one second.
---

# anchor

Use this FIRST, before grep, read_file or any other search.

## How to run

Call run_skill_script with skill_name set to anchor, file_path set to scripts/anchor.py, and args set to a dict with one key, query. The query is one plain string.

Put in the query every code name you can see in the issue, copied exactly, separated by spaces: function and class names, dotted names such as Router.add_api_route, exception names, file paths ending in .py, and the function names from any traceback lines. Copy them letter for letter, whatever language the rest of the issue is in. Leave out ordinary words, brackets, quotes and backticks.

Example query: APIRoute.get_route_handler jsonable_encoder exclude_none fastapi/routing.py

## What it prints

- ANCHORS: lines of the form symbol -> path:line, most specific first, each saying where the evidence came from.
- FILES: the files most likely to need the change, best first.
- NO_ANCHOR: none of the names exist in this repository.

## What to do with it

1. Read the definition at the first ANCHOR line (read_file starting a few lines before that line).
2. If the fix is not there, check the next two anchors before searching anywhere else.
3. Then use get_code_neighbors on the best symbol to see its callers and callees.
4. If it printed NO_ANCHOR, use your normal search.

The ranking is a strong hint, not a guarantee: the file to change is usually among the first three FILES, not always the first.
