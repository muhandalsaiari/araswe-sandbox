---
name: anchor
description: Points to the lines most likely to need the fix, before any searching. Give it the code names from the issue and it prints up to three files, each with the exact lines to read. Deterministic, no model call, about one second.
---

# anchor

Use this FIRST, before grep, read_file or any other search.

## How to run

Call run_skill_script with skill_name set to anchor, file_path set to scripts/anchor.py, and args set to a dict with one key, query. The query is one plain string.

Put in the query every code name you can see in the issue, copied exactly, separated by spaces: function and class names, dotted names such as Router.add_api_route, exception names, file paths ending in .py, and the function names from any traceback lines. Copy them letter for letter, whatever language the rest of the issue is in. Leave out ordinary words, brackets, quotes and backticks.

Example query: APIRoute.get_route_handler jsonable_encoder exclude_none fastapi/routing.py

## What it prints

- READ FIRST: up to three files, best first, each with a line range such as lines 120-159.
- NO_ANCHOR: none of the names exist in this repository.

## What to do with it

1. Call read_file on file 1 with exactly that line range.
2. If the fix is not there, read file 2 the same way. Stop there.
3. Then write your PLAN and make your first edit. Do not keep exploring.
4. If it printed NO_ANCHOR, use your normal search.
