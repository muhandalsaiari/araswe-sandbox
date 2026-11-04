# araswe anchor kit

Model-free, language-agnostic localization for the Gemma 4 paper (plan v5 §4–5.3).

```
skills/anchor/SKILL.md            the skill manifest (brace-free, name: anchor)
skills/anchor/scripts/anchor.py   the script (stdlib only, ~0.1–0.2 s on fastapi/rich)
tools/eval_localization.py        Experiment A: 9 rankers x one issue-text variant
tests/test_anchor.py              12 unit tests (incl. EN vs AR identical output)
```

## Install (on your PC, in WSL)

```bash
mkdir -p ~/araswe && tar -xzf /mnt/c/Users/user/Downloads/araswe_anchor.tar.gz -C ~/araswe && cd ~/araswe/araswe_anchor && python3 -m unittest discover -s tests
```
Expect `Ran 12 tests ... OK`.

## Step 1 — the reproduction gate (English, all 129 tasks)

```bash
python3 tools/eval_localization.py --data ~/araswe/data --cache ~/araswe/cache/pysnaps --label en --out ~/araswe/results/expA --reproduce --verbose
```
First run extracts the package source from every snapshot (several minutes; cached after that).
`GATE: PASS` means our re-implementation of findfile matches its published numbers within
1.5 points. If it says FAIL, stop and fix before trusting anything else.

Acceptance for the anchor (plan §4): `anchor` top-3 at or above `findfile_ids_only` (~53%).

## Step 2 — a translated variant (after translation exists)

```bash
python3 tools/eval_localization.py --variant ~/araswe/translations/ar_mix_tasks.jsonl --label ar --out ~/araswe/results/expA
```
The variant file is a tasks.jsonl with the same instance_ids and translated `problem_statement`.

## Step 3 — the skill inside the harness

Copy `skills/anchor` into an agent folder (e.g. `fixes/agents/araswe_12b_anchor/skills/anchor`),
add to its `agent.yaml`:

```yaml
skills:
  - skills/anchor
```

and add the 3-sentence rule to its `prompts/system.md`. **Before that, read
`fixes/agents/skill_probe/` to see exactly how `run_skill_script` passes arguments**
and adjust the "How to run" line in SKILL.md if needed. The script accepts the issue as
one argument, several arguments (joined), `--issue-file PATH`, or stdin.

## Notes
- Only ASCII code-like tokens are used, so prose in any language is ignored by design.
- Names the reporter defines in their own example code are dropped (they are not library code).
- findfile functions in `eval_localization.py` are re-implemented from the public notebook
  "LocBench + findfile: Find the File First" (nobanks, Kaggle, Apache-2.0); cite it.
