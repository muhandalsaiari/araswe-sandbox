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
