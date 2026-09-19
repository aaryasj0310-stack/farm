# SW P1 — committed-herd purchase workload experiment

**Status: experiment rejected for production promotion. Do not merge this branch as-is.**

- Production control: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- P1 treatment runtime: `b89c8381b341d43c9e81e0701fd8d39edbc8aaaa`
- Results commit: `a4d374c2d1077a5da15d01cf7c8e816925624e53`
- Engine: kaggriculture 1.32.7
- Experiment: 20 matched seed/opponent pairs, 40 complete games.
- Raw results: `simulations/experiments/results/sw_p1_committed_herd_20pair.json`

## Hypothesis and isolated change

P1 makes **only the SW land PURCHASE gate** count observed livestock and built housing as committed work, instead of promoting the desired 12-sheep target to an unavoidable NE work obligation. The default flag `SW_P1_PURCHASE_COMMITTED_HERD_ONLY=False` retains production behavior. Activating the switch does not alter activation, feed capacity, treasury reserve, land timing, ROI, market arbitration, crop portfolio, or worker partition.

The default evaluator still reserves desired-herd workload; the purchase-only call uses `reserve_desired_herd=False` in the treatment. P2 (duplicate seed economic deduction) has **not** been applied.

## Validation

- Source/submission module parity and syntax check passed.
- Focused SW/land tests: 22 passed.
- Full agent regression suite: 995 passed.
- Canonical submission zip built and an isolated 720-step game completed.
- Exact-SHA 20-pair A/B job passed and committed the structured result artifact.

Passing tests establishes executable, well-isolated behavior. A single package score is not economic A/B evidence.

## Paired results

| Metric | Control | P1 |
| --- | ---: | ---: |
| Mean score | $102,919.75 | $82,733.95 |
| Engine-confirmed SW acquisitions | 0/20 | 15/20 |
| Starvation observations | 205 | 560 |
| Unwatered crop observations | 2,826 | 5,091 |
| Negative-cash observations | 0 | 0 |
| SW planted tile-days (hour-23 pre-action snapshots) | 0 | 2,966 |
| SW watered plant-days (same snapshots) | 0 | 2,129 |
| SW harvest **attempts** | 0 | 613 |

Paired candidate-minus-control mean score: **-$20,185.80**; median: **-$24,482**; approximate 95% t confidence interval: **[-$26,608.50, -$13,763.10]**; **0 wins / 5 ties / 15 losses**. No matched game had an execution error. The five ties correspond to episodes with no SW acquisition in either arm.

## Interpretation and next gate

The observed purchase transition proves the desired-herd workload can be decisive for non-acquisition in this evaluated production state distribution. It does **not** prove that disregarding the aspirational herd is strategically safe: acquired SW creates worker/cash/land-use consequences that the present evaluation did not predict.

Both starvation and unwatered crops increased substantially while SW acquisition and SW planted tile-days rose. Those are associations within the paired intervention, not a complete attribution of the score loss to one specific scheduler line; inspect paired per-day task/worker traces before deciding whether the cause is worker partition, travel, seed/feed displacement, crop selection, or another downstream effect.

**Do not roll out P1, do not add P2 to this same arm, and do not respond by force-buying SW.** Next perform an audit of the post-acquisition worker partition and SW activation/serviceability mismatch, then build separately controlled arms that require capacity/safety proof before purchasing land. A P2 economic-payback correction can be evaluated independently, but removing an economic restriction without solving demonstrated downstream losses is not an appropriate production promotion criterion.

Measurement cautions: SW harvested actions are counted as **attempts**, not engine-confirmed yield; a fungible product sold from the shed cannot be attributed reliably to SW without provenance tracking. Day-23 utilization snapshots are not a fully integrated every-turn tile-day ledger. Use paired final scores for the aggregate economic comparison, not a claimed direct SW revenue figure.
