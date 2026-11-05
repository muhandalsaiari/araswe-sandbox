<!-- contract: handoff note for the next session. Facts and commands only; the journal stays the source of truth. -->
# Handoff: forgiving-edit skill (2026-11-04)

## For a Claude Code desktop session on the user's machine
- Open the folder `~/araswe/fixes`. That is this repo, checked out locally.
  - The git remote is `mine` and the branch is `araswe`. Pull with `git pull mine araswe` and push with `git push mine araswe`.
- You run on the machine that holds the traces, runs and envs, so run the commands below yourself. Do not ask the user to paste
  output. Earlier cloud sessions had to work that way; you don't.
- The local model server is Bionic (llama.cpp-based) on port 1235, with Reasoning Budget 1024. The user sets that budget in
  the Bionic app; you cannot.
- Follow CLAUDE.md:
  - `tools/jgrep.sh` or `grep -a` for journal reads. The journal is binary-flagged, so plain grep prints "binary file matches".
  - Dates from `date -u`.
  - Append-only journal, with a PROBE line after reading the run.
  - Banned words (rule 10).
  - Explain to the user in plain language, one step at a time.

## Where it stands
- The skill: `tools/forgiving_edit/` (script, SKILL.md, 13 unit tests, real-code stress test). No wrong edit in
  about 3,200 damaged edits on fastapi + requests.
- The harness `edit_file` already undoes JSON escaping and indentation. The skill adds four things:
  - a backslash before a line break, and `\'`;
  - blank lines that differ;
  - JSON layers mixed with stray backslashes;
  - on failure, the closest real lines with line numbers.
- Agent under test: `agents/araswe_12b_out2k_tb1k_fedit`, a copy of `araswe_12b_out2k_tb1k` plus the skill and one prompt bullet.
  - Its copy of `edit.py` is the version BEFORE the json1/json2 steps, kept that way because the run below uses it.
- Run `fedit_screen01` was launched on the user's machine at about 20:30Z, for 20 screen_01 tasks. When it ends it writes
  `runs/fedit_summary.txt`.

## Step 1: read the run (on the user's machine)
```bash
cat ~/araswe/fixes/runs/fedit_summary.txt   # if missing: tail -n 20 runs/fedit_screen01.log (the run may have stopped overnight)
```
```bash
cd ~/araswe/fixes && git pull mine araswe && python3 -I tools/paired_runs.py fedit_screen01 out2k_tb1k_screen01 out2k_tb1k_screen01_r2
```
If the summary file is missing, check the run with `tail -n 20 runs/fedit_screen01.log`.

## Step 2: decide
Baselines: out2k_tb1k_screen01 resolved 6/20 (4 within the clock), and r2 resolved 8/20 (4 within the clock).
A gap of 1–2 tasks on 20 is noise, so go mainly by the mechanism counts in fedit_summary.txt.
- `failed_edit_next_skill` is near 0 while `failed_edit_next_edit_file` is high: the model ignores the prompt bullet.
  Fix the bullet before anything else. For example, mention it inside the tool-failure guidance, or say "after ONE failure".
- `skill_script_error` or `skill_tool_error` is above 0: look at the `--show` examples. The argument plumbing is wrong.
- `skill_edited` is above 0 and `not_edited_then_landed` is above 0, and resolved within the clock is not below the baselines: keep it.
  1. Copy `tools/forgiving_edit/skills/edit` over `agents/araswe_12b_out2k_tb1k_fedit/skills/edit` to get the json steps.
  2. Run screen_01 a second time, as fedit_screen01_r2, before trusting it.
- Write the result to `journal.md` as a PROBE line, with the numbers.

## Run command (same settings as before; Bionic Reasoning Budget 1024)
```bash
cd ~/araswe/fixes && IMAGE=swebench-sandbox-local:v2 MODEL_PORT=1235 SERVED_MODEL_NAME=google/gemma-4-12b-qat RUN_ID=<run_id> CONCURRENCY=2 nohup envs/harness/bin/python -I kits/swe-agent/run/run_tasks.py agents/araswe_12b_out2k_tb1k_fedit runs/<run_id> screen_01 > runs/<run_id>.log 2>&1 &
```

## Also open
- r2/fastapi_14786: 198 `edit_file` calls with only filepath, a loop. The framework rejects them before they run, so they
  cost LLM calls but not tool-call budget. Not addressed yet.
- Journal lines stamped 19:25Z–22:30Z on 2026-11-04 carry clock times that were not taken from the shell. A CORRECT line records this.
