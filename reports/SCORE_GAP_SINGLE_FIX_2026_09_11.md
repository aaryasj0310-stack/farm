# Single-change score experiment — 2026-09-11

**Decision: REVERTED.** The urgent-dispatch candidate reduced mean cash score by 47.1 (0.10%), lost on 7/10 seeds, and lowered the worst score by 1,090 (2.49%). No strategy change remains in `submission/`.

## Selected root cause and exact attempted fix

The selected hypothesis was inefficient urgent-task ownership, within `submission/execution/task_scheduler.py::assign_tasks()` (original lines 902–944). Its urgent dispatch tier preferred any worker without a sticky mission over a closer capable mission owner. The subsequent sticky-resumption tier could also dispatch the old owner to an operation already assigned by the urgent tier.

Three test cases reproduced this on the unchanged executable source: immediate WATER was passed over for movement, and a promoted urgent operation acquired two workers, whether its original owner or another worker was closer.

The only production edit changed worker selection to minimum Manhattan distance across already-eligible free workers, retaining non-mission preference on distance ties, and released matching old operation/target ownership before sticky resumption. No priority levels, inventory eligibility, hiring, crop selection, feed budgets, land gates, market rules, or safety fallback code changed.

The defect is reproducible, but the hypothesis that this was a high-leverage score improvement was **not supported**. It is not established as the largest score bottleneck.

## Paired results

Each candidate and opponent ran from separate processes with fresh module state. Both phases used the frozen original `submission/` package as the seat-1 opponent; the evaluated player always occupied seat 0. This is a local competitive benchmark, not evaluation against private leader code.

| Seed | Before | Candidate | Delta |
|---|---:|---:|---:|
| 11 | 48,023 | 47,411 | -612 |
| 101 | 43,763 | 42,673 | -1,090 |
| 202 | 58,302 | 56,941 | -1,361 |
| 303 | 44,799 | 45,454 | +655 |
| 404 | 52,700 | 57,007 | +4,307 |
| 42 | 44,914 | 42,982 | -1,932 |
| 777 | 46,318 | 45,039 | -1,279 |
| 907 | 48,744 | 48,512 | -232 |
| 1234 | 47,316 | 49,773 | +2,457 |
| 2026 | 45,255 | 43,871 | -1,384 |
| **Mean** | **48,013.4** | **47,966.3** | **−47.1** |
| **Worst** | **43,763** | **42,673** | **−1,090** |

The initial five seeds showed +0.77% mean gain with three losses. The same unchanged candidate was extended to ten seeds to resolve that mixed result; no strategy tuning occurred between batches.

## Operational metrics

Percentages and idle counts below are per-match averages; death/missed-feed counts are totals over ten matches.

| Metric | Before | Candidate |
|---|---:|---:|
| SW purchase day | 11.8 | 11.8 |
| SW occupancy after unlock | 49.69% | 49.29% |
| Successful non-movement action utilization | 25.28% | 25.22% |
| Travel share | 64.52% | 64.45% |
| Idle PASS actions per match | 742.6 | 751.3 |
| Ineffective non-PASS actions, total | 137 | 141 |
| Animal deaths | 0 | 0 |
| Missed feeds, animal-days | 232 | 216 |
| Missed feeds before terminal day | 228 | 213 |
| Terminal-day missed feeds | 4 | 3 |
| Crop deaths from dehydration | 0 | 0 |
| Crop lifecycle expirations, separately counted | 225 | 227 |
| Agent fallbacks / failed terminal statuses | 0 / 0 | 0 / 0 |

SW occupancy counts PLANT, COOP, and PASTURE tiles (including structures holding animals) over all 25 SW tiles at every observed turn after acquisition. It includes empty structures, so it is not equivalent to productive output.

Action utilization counts engine-observed state-changing unit actions excluding cardinal movement; travel and PASS use all engine unit-action calls as denominator. Missed feeds are sampled inside the engine immediately before daily animal refresh, after unit actions, not from pre-action observations. Dehydration deaths are PLANT-to-WEED transitions during daily refresh; natural expiration is reported separately and does not by itself imply lost yield. Animal losses are observed at the engine refresh, not inferred from final herd size.

**Horizon disclosure:** runs use `episodeSteps=721`, yielding 720 action turns and terminal Day 30 Hour 0. The installed default is 720 observations and stops at Day 29 Hour 23. Saved Day-29-Hour-23 cash equals final cash in all 20 games, so the additional terminal action did not change any reported score. Operational totals include that action/refresh. Aborted horizon-validation attempts are excluded from the JSON results.

## Why rejected

A 0.07 percentage-point reduction in travel and 16 fewer missed animal-day feeds did not translate into score. Average productive utilization and SW occupancy declined, idle actions increased, and most paired scores fell. More aggressive urgent preemption plausibly interrupts useful multi-turn work; the benchmark establishes the net loss, not an exact attribution of every lost coin. Retaining a correctness-motivated change despite these results would contradict the score-first acceptance rule.

## Validation and final state

- Before implementation: all three new regression cases failed for the expected dispatch errors.
- Candidate: 492 tests passed with seven reference-data skips; after supplying the existing NPZ to the isolated test copy, all nine forecast tests passed, including those seven. Thus all 499 unique candidate-suite tests passed across these runs. The three targeted cases also passed directly.
- After reverting: 38 dispatch, sticky-mission, feed-zoning, and emergency regressions passed; 458 unrelated cases were deselected.
- `git diff --exit-code -- submission` succeeded after reversal. All original executable source behavior is restored.
- The user's pre-existing architecture-file edits were left intact.

Retained files: `scripts/benchmark_score_gap.py`, `scripts/test_submission_source.py`, this report, and the experiment directory `simulations/results/score_gap_20260911/` containing immutable before/after packages, candidate patch, raw per-game JSON, logs, and archived candidate regression cases. No `agent/`, root submission bundle, or `dist/` strategy was changed.

## Next highest-value issue

**SW acquisition missing the livestock investment window.** In 9/10 baseline seeds SW was acquired on Day 12 and the Day-15 herd remained only two cows; seed 404 acquired SW on Day 10 and reached five cows plus four sheep. `C4_LIVESTOCK_CUTOFF_DAY = 12`, enforced by `get_animal_targets()` and `OrderBuilder.reinvest_livestock()`, closes animal buying on Day 12. This is stronger observed evidence of lost production than the attempted dispatch change.

Next pass should test one narrowly scoped way to acquire SW before that existing cutoff while preserving hire/feed reserves. Do not simultaneously relax the livestock cutoff, expand herd caps, or redesign routing. Seed 404 is observational support, not causal proof, because shop RNG also differs.

## Reproduction

Use the installed Python runtime, prefixed with `rtk proxy`:

```text
python scripts/benchmark_score_gap.py --phase before --seeds 11 101 202 303 404 42 777 907 1234 2026
python scripts/benchmark_score_gap.py --phase after --seeds 11 101 202 303 404 42 777 907 1234 2026
python scripts/test_submission_source.py -q
python -m pytest simulations/results/score_gap_20260911/rejected_tests -q
```

The benchmark resumes completed seeds and checks saved source hashes. Its `after` phase evaluates the archived rejected candidate, not the restored live package.
