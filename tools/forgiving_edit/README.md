# forgiving edit kit

A skill that makes a failed `edit_file` call land when the only problem is stray escaping or blank lines,
and otherwise shows the model the real lines to copy. Built from the 2026-11-04 journal measurements.

```
skills/edit/SKILL.md            the skill manifest (name: edit)
skills/edit/scripts/edit.py     the script (stdlib only)
tests/test_edit.py              unit tests
../forgiving_edit_replay.py     offline replay over real traces; imports edit.py, so it measures this exact code
```

Order of attempts, first unique match wins: exact, strip `\"`/`\'`, also drop a backslash before a line
break, also turn a typed backslash-n into a line break, then the same non-blank lines in order with blank
lines ignored. New text gets the same cleaning. A `.py` result that no longer compiles is refused. No
match: nothing is written and the closest block of the file is printed with line numbers.

Test: `python3 -m unittest discover -s tools/forgiving_edit/tests`

Install into an agent: copy `skills/edit` to `agents/<name>/skills/edit` and list `skills/edit` under
`skills:` in its `agent.yaml`.

## What the harness edit_file already forgives (read 2026-11-04)

The harness `edit_file` (swegemma/edit.py -> adk_eval_core/editing/edit.py `apply_replacement`) tries, in
order: exact; flexible (per line, trailing spaces ignored, then leading and trailing spaces ignored); regex;
unescaped (one or two layers of JSON escapes: `\"`, `\\`, `\uXXXX`, and in the full layer also `\n`, `\t`,
`\r`, `\/`, each followed by exact then flexible). On failure it says only "old_string not found".

Not covered by it, and covered here: a backslash right before a real line break (not a JSON escape, so
its regex leaves it), `\'`, blank lines that differ, and on failure the closest real block with line
numbers. Every edit counted as failed in the replay was already refused by that tool, so the replay's
rescues are on top of what it does. What the skill does not repeat: indentation-relaxed matching (no
unrescued edit in the 80 screen_01 runs was a whitespace-only miss).
