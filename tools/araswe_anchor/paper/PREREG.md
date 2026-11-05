# Pre-registration

This file binds once its SHA-256 is posted on the paper-track forum. No full-run outcome had been seen when it was written. The 8 pilot tasks are not in any confirmatory set.

## What is already known, so it is not confirmatory

Experiment A (competition set), the signal audit and the SWE-bench Lite replication ran before this file. They are reported as exploratory.

- Competition set, `findfile_nolist` top-3: EN 72, languages 62 to 68.
- SWE-bench Lite, 296 tasks: EN 56, languages 55 to 58, none separated from EN.
- Prose adds 14 points beyond code on the competition set and 3 on Lite.
- Plan v5's A1 to A3 are not claimed as pre-registered tests.

## Part 1: agent study

**Model and server.** Gemma 4 12B QAT, GGUF Q4_0, Bionic, port 1235. The largest prompt in the pilot was 16,921 tokens.

**Settings.** Temperature 0, top_p 0.95, seed 42, max output 2,048, thinking budget 1,024, concurrency 2. Budget: 30 tool calls, 40 turns, `KAGGLE_CLOCK=off`, 25-minute guard. The call budget is the binding limit.

**Arms, each task runs all five.**

| Arm | Issue text | Agent |
|---|---|---|
| EN | original | `agents/araswe_paper_base` |
| AR | AR-MIX | `agents/araswe_paper_base` |
| EN+anchor | original | `agents/araswe_paper_anchor` |
| AR+anchor | AR-MIX | `agents/araswe_paper_anchor` |
| AR+TF | AR-MIX translated back by the same 12B, one extra call, tokens counted | `agents/araswe_paper_base` |

AR-MIX is the DeepSeek translation in `ar_mix_full.jsonl`, with code and identifiers left in English. The anchor agent differs from the base agent only by the skill, a first step that calls it, and one line on its arguments.

**Tasks.** Run `tasks_60.txt` first, then `tasks_ext.txt` in file order, up to 115 tasks in all. Stop adding tasks after 60 hours of run time, whatever the results. Tasks run in blocks, each block through all five arms, so a stop leaves no half-finished arms. Only tasks complete in all five arms are analysed. The list order was fixed before any full run. Six excluded tasks: 2 where an empty patch already passes, 4 where the real fix cannot pass on Python 3.13.

**Retest.** The 10 tasks in `retest_10.txt` (seed 42 sample of `tasks_60.txt`), EN and AR arms, run a second time. Agreement is reported.

**Primary metric.** Gold-file edit recall: 1 if the final diff touches a non-test file in the gold patch, else 0.

**Secondary metrics.** Turns to first gold-file read (capped at 31), resolved, total tokens.

**Failed runs.**
- A run with 0 tool calls, or one aborted by a server error (HTTP 400/500 from the engine, `terminated`), is rerun once.
- The primary analysis uses the rerun. A second failure counts as 0.
- A sensitivity table counts every first-try abort as 0.
- The agent's own failures (budget, no `submit_patch`) are never rerun.

## Hypotheses and verdicts

Holm correction across H1 to H4, alpha 0.05. The equivalence margin is 10 points, set from the pilot: on the primary metric, 0 to 2 of 8 tasks differed between arm pairs. At 2 of 8 the 90% interval is about ±7.7 points at 115 tasks and ±10.6 at 60, so a stop near 60 tasks may leave some verdicts NOT SHOWN.

Each test reads one of three verdicts:
- **HOLDS:** the stated test passes after Holm, in the predicted direction.
- **FAILS:** the 90% interval of the effect lies inside ±10 points.
- **NOT SHOWN:** anything else.

H4 is a non-inferiority claim, so it has its own rule. Effect = AR+anchor minus AR+TF. HOLDS: the lower 90% bound is above -10. FAILS: the upper 90% bound is below -10. NOT SHOWN: anything else.

| ID | Claim | Test |
|---|---|---|
| H1 | AR lowers gold-file edit recall vs EN, anchor off | McNemar exact |
| H2 | Anchor raises EN recall | McNemar exact |
| H3 | The EN minus AR gap is smaller with anchor | Per-task difference-in-differences, one-sided sign-flip, 10,000 flips, seed 42 |
| H4 | AR+anchor is non-inferior to AR+TF on recall | TOST, margin 10; tokens by Wilcoxon |

**What each H1 outcome means, written before the data.**
- HOLDS: the ranker loss reaches the agent. H3 then says whether the anchor repairs it.
- FAILS: the agent absorbs the ranker loss. That is the finding, and H3 is not read as repair.
- NOT SHOWN: we report the interval and claim neither.

Everything else is exploratory.

## Part 2: what decides whether prose matters

**Data.** SWE-bench test split minus Lite, minus `psf/requests`. Small stratum: under 100 `.py` files in the task snapshot. Large stratum: over 300. Up to 300 tasks per stratum, seed 42. Same translator and six languages. CPU only. Metric: `findfile_nolist` top-3, mean change over six languages. Only issue text from this data stays local; we ship ids and numbers.

| ID | Prediction | Test |
|---|---|---|
| S1 | The loss is larger in small repos than large | Difference of stratum means, interval from a bootstrap over repos then tasks |
| S2 | Tasks where prose adds a hit (full hits, code-only misses) lose more than other tasks | Same, within each stratum |
| S3 | At the same size, issues with fewer bare identifiers lose more | Median split inside each stratum, median taken from this data |

HOLDS: the 95% interval excludes zero in the predicted direction. FAILS: the 90% interval lies inside ±3 points. NOT SHOWN: anything else. S1 to S3 use Holm. If S1 fails and S3 holds, the paper names issue style, not repo size.

Limit stated in advance: few repos are small, so the repo-level interval may be wide and S1 may read NOT SHOWN.

## Deviations from plan v5

- Thinking budget 1,024, not 4,096: matches the settings tested in the pilot.
- Concurrency 2, not 1.
- Up to 115 tasks, not 60: the pilot's 265 seconds per run puts 595 runs at about 44 hours.
- A1 to A3 are exploratory, because they ran before this file.
- The translator is DeepSeek. The disclosure line will say so.
