<!-- docs/roadmap.md contract
WHAT: the plan for both Gemma 4 tracks up to their deadlines: what is done, what is next, what decides each step.
The full design is gemma4-paper-plan-v5.md (the user's Downloads folder, not in this repo). The journal stays the event history.
Update in place when a date or status changes; date every update.
-->
# Roadmap, as of 2026-11-05

Goal: win both tracks. **The paper comes first until 12 Nov** (plan v5 rule). One GPU, so paper runs take it first.

| | Paper track | Main competition |
|---|---|---|
| Deliverable | Kaggle Writeup, 3,000 words at most | `submission.zip`, scored on about 120 hidden tasks |
| Deadline | 12 Nov 23:59 UTC; aim for 11 Nov, ties go to the earlier entry | Entry and merger 25 Nov, final 2 Dec 23:59 UTC |
| Limits | 2 writeups per team, submit one | 1 submission a day, 1 pending at a time, 2 final picks |

## Where we are against plan v5

| Item | Status |
|---|---|
| Main sub #1 (`araswe_sub01`, baseline) | Failed: Notebook Timeout, no score (Kaggle page, 5 Nov). Needs a fix before any resubmission |
| Anchor skill, Exp A harness, findfile reproduction gate | Done, gate passed |
| Translations | All 6 languages done in mix mode (zh 1 retry); back-translation drift check to do |
| Exp A | EN, AR-MIX, AR-FREE done, paired test done |
| Anchor through the harness on 3 tasks | English done (`runs/anchor12b_smoke3`, 4 Nov): valid calls, 0 of 3 resolved on hard tasks. Arabic check `anchor3` running |
| PREREG, 8x5 pilot, Arabic agent runs | Pilot running since 5 Nov; PREREG and full runs next |
| Host question on releasing translations | Answered 5 Nov: publish translations keyed by instance_id, link the original for verbatim parts. The user replied we release prose with placeholders plus a restore script from `tasks.jsonl`; that script is still to build |
| Arabic reader | Not recorded; the user to confirm |

About a day and a half behind. The last two days went to the 12B edit work, which is not on the paper path.

## Three problems to settle before the writing

1. **The core claim needs changing.** Exp A on Arabic: A2 holds (anchor flat at 53). A1 is borderline (findfile no list 72 to 64, -8, the plan asked for 10 or more; tuned -10.4). A3 fails: anchor 53 against findfile 64, and findfile stays ahead in Arabic (+11.2, p=0.034). So "the anchor catches up or overtakes" is not what the data says. Supported today: prose rankers lose 8 to 10 points in Arabic, identifiers lose none, and prose still leaves them ahead. Anchor is blind on 37% of tasks. Next: test a hybrid, and see whether the other 5 languages match.
2. **The 12B calls the anchor in English; Arabic is untested.** In `anchor12b_smoke3` it called the anchor with valid arguments on all 3 tasks when the prompt made it step 1, unlike the fedit2 repair skill. On fastapi_14099 it repeated the call about 8 times in an 81-call run, so watch for loops. If Arabic fails, the local paper arms can put the anchor output into the issue text with a variant task file, stated plainly in the paper. That route would not carry over to a Kaggle submission.
3. **Pre-registration must stay honest.** A1 to A3 results were seen before any PREREG exists, so only Exp B+C can be called pre-registered. Commit PREREG and post its hash before the pilot's full runs start.

## Plan attack, 5 Nov: weak points and fixes

| Weak point | Fix |
|---|---|
| "Nobody has measured this" is false: CrosLocator 2014, Hayashi 2023, MAPS | Read and cite them. New novelty: which signals survive, by script, for model-free localizers and a small agent |
| Agents may not care: MAPS reports little change on translated SWE-bench, so H1 and H3 may be null, and 60 tasks is weak | Write both outcomes into PREREG. "Retrievers break, the agent copes" is also a result |
| Anchor adds nothing as a ranker (equals `findfile_ids_only`, invariant by construction, loses everywhere) | Demote to control and agent tool. Lead with the signal audit: split the issue into traceback, code span, code block, prose |
| Translations protect the code, real issues may not | AR-NAT subset, Arabic reader, state the limit. Real Chinese issues if time allows |
| "Just translate it back" | Tested: wins back about half (64 to 67, 62 to 67), still -4.8, p=0.031. Keep as a row; check the bm25 ar drop; add the other 4 languages |
| 4 repos, 1 model: weak on generality. A rival shows a hub prior scores about 0.71 on these repos and about 0.10 on SWE-bench Lite | Top priority after the pilot: replicate Exp A on SWE-bench Lite (12 repos, CPU only). Rivals set this bar |
| Model outage counts as failure (0-call rows) | Before full runs: after each condition, list 0-call rows and rerun them |
| Plan says Claude translated, DeepSeek did | Fix the disclosure and PREREG |
| Main competition has no score; skill submissions may score 0; 31B LoRA unproven | Next slot: baseline with a shorter time cap, then anchor. Consider E2B or E4B as a final pick for the small-model bonus |

## Bar set by rival releases (jaredga, 5 Nov)

- `reproduce_numbers.py`: recompute every paper number offline from shipped per-task rows, no GPU, plus `MANIFEST.sha256`.
- PREREG rules that read HOLDS, FAILS or NOT SHOWN, hashed before each run.
- A placebo arm if the pilot leaves time: the anchor returns another same-repo task's result. It shows whether the content helps, not the extra step.
- SWE-bench Lite: report with and without `psf/requests`, which is a competition repo. Ship ids, numbers and scripts for Lite, not its issue text.

## SWE-bench Lite result (5 Nov)

- The Exp A loss did not replicate: `findfile` top-3 is 56 in English and 55 to 58 in six languages, none separated, on 296 tasks.
- Anchor scores 62 on Lite, above `findfile`, the reverse of the competition set.
- Prose adds 14 points beyond code on the competition set and 3 on Lite. The translation loss tracks that in both sets.
- Two suspects, confounded: repo size (under 100 files: about -8 in both sets) and issue style (bare identifiers per task: 8.9 on Lite, 1.8 on the competition set).
- All splits are post hoc. Next: pre-register a test on SWE-bench full minus Lite.

## Paper: day by day

| Day | Work |
|---|---|
| Thu 5 | Anchor on 3 Arabic tasks. Translate the other 5 languages (CPU and API, GPU stays free). Start the 8x5 pilot overnight |
| Fri 6 | Exp A on all languages, hybrid ranker, rewrite the core claim. Pilot to compute check. Commit PREREG, post hash. Start full runs. Main sub #2 (anchor) if #1 is scored |
| Sat 7 to Mon 9 | Full runs, spot-check 3 trajectories per condition daily. Arabic reader's 40 ratings, AR-NAT subset. Write Intro, Related, Resource, Exp A |
| Tue 10 | Pre-registered tests as written, then labelled exploratory analysis. Figures |
| Wed 11 | Finish the writeup, reproduction notebook, links. **Submit** |
| Thu 12 | Buffer only |

Compute: fedit2 runs took about 300 s per task at concurrency 2, Reasoning Budget 1024, so 320 runs is about 27 h. Plan v5 set budget 4,096 and concurrency 1, which will be slower; the pilot gives the real figure. Cut order is in plan v5 section 5.6: never drop a 2x2 cell.

## Main competition: 13 Nov to 2 Dec

| Dates | Work |
|---|---|
| 13 to 19 Nov | Rollouts on Kaggle 4xL4 (check quota 13 Nov), best 31B config, keep passing trajectories |
| 20 to 26 Nov | LoRA SFT, rank 8 to 16, with held-out tasks. Target the stray-backslash habit too: keep clean edits, drop or repair leaking ones. Submit only if it beats base on the holdout |
| By 25 Nov | Entry and team merger close |
| 27 Nov to 2 Dec | Second round if time allows, worst-case runtime 11 h or less, pick 2 finals. Small-model bonus counts only if E2B or E4B is a final pick |

LoRA notes: training needs a rented GPU or Kaggle quota; the 4070 SUPER has 12 GB. The E2B LoRAs in this repo's history (the upstream author's, not this fork's) did not beat base (16 and 21 of 369 against 24). The E2B adapter ran at 0.65 to 0.73x base speed on L4, so check speed against the 12 h limit. Test on the vLLM path, not Bionic.

## Parked until after 12 Nov

- Forgiving-edit skill: no clear gain over two runs (`journal.md`, 2026-11-05). Its edit-failure counts stay for the LoRA data and the paper's limitations.
- Patched local `edit_file` test: cannot reach Kaggle, and would take GPU time from the paper.
- `fastapi_14786` filepath-only loop.
