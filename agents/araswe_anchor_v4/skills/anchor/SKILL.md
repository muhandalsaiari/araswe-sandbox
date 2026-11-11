---
name: anchor
description: Points to the lines most likely to need the fix, before any searching. Give it the code names from the issue and it prints the code of the two best matching places. Deterministic, no model call, about one second.
---

# anchor

Use this FIRST, before grep, read_file or any other search.

## How to run

Call run_skill_script with skill_name set to anchor, file_path set to scripts/anchor.py, and args set to a dict with one key, query. The query is one plain string.

Put in the query every code name you can see in the issue, copied exactly, separated by spaces: function and class names, dotted names such as Router.add_api_route, exception names, file paths ending in .py, and the function names from any traceback lines. Copy them letter for letter, whatever language the rest of the issue is in. Leave out ordinary words, brackets, quotes and backticks.

Example query: APIRoute.get_route_handler jsonable_encoder exclude_none fastapi/routing.py

## What it prints

- The code itself: up to three short numbered pieces from each of the two best files, then the path of a third file.
- NO_ANCHOR: none of the names exist in this repository.

## What to do with it

1. Look for the fix in the code it printed. Do not read_file those lines again.
2. Write your PLAN and make your first edit in your next call or two.
3. Read other lines only if the place you must change is not in the printed code.
4. If it printed NO_ANCHOR, use your normal search.
