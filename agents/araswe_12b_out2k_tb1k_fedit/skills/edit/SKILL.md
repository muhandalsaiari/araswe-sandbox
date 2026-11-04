---
name: edit
description: A forgiving edit for when edit_file says old_string was not found. It removes stray backslashes the file does not have, ignores blank-line differences, edits only when the text matches exactly one place, and otherwise prints the real lines to copy. Deterministic, no model call, under a second.
---

# edit

Use this when edit_file failed with "old_string not found". Do not retry edit_file on the same place.

## How to run

Call run_skill_script with skill_name set to edit, file_path set to scripts/edit.py, and args set to a dict with three keys: filepath, old_string and new_string. Use the same three values you gave edit_file.

## What it prints

- EDITED: the change is made. A short diff follows. Go on with the fix.
- NOT EDITED, matches several places: add one more line from around the place you mean to old_string and run it again.
- NOT EDITED, not in the file: the closest lines of the file follow, each with its line number and a bar in front. Copy old_string from those lines exactly, without the numbers and bars, and run it again.
- NOT EDITED, would break Python syntax: fix new_string (real line breaks, quotes without backslashes, the same indentation as the lines around it).
