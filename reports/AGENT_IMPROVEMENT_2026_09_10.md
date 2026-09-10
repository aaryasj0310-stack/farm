# Agent improvement experiment — 2026-09-10

## Scope and baseline

Baseline: clean commit `a98e2b367b22ffe40a32ebf74e4870c0188ff354`, branch
`v5.12-c6-production`. The unchanged standalone submission was preserved as
`simulations/results/improvement_baseline_a98e2b3.py`.

Baseline SHA-256:
`42bb123d0a549a0499b2603063f01619b1b2d6f71cd549d16c1e7d201802f66f`.

The earlier leader comparison was a hypothesis, not an experimental result.
Inspection and full-season diagnostics showed that delivery and service capacity
must improve before simply increasing the pasture or strawberry caps.
No live leaderboard rank or performance against private leader code is claimed.

## Evidence and implementation

1. **Missed reinvestment window.** On the controlled baseline seed 101, the farm
   had only two cows and seven empty pastures at the end of Day 11 despite holding
   12,591 coins. Market purchases occurred only at Hour 0; the Day-12 animal cutoff
   prevented using the later harvest proceeds. `OrderBuilder.reinvest_livestock`
   now permits freshly recomputed animal/feed purchases during Hours 2–18 after
   SW is owned and before the existing cutoff. The planner still counts owned
   and carried animals and reserves future wages; the builder retains its budget,
   housing, and shed checks. The morning hire schedule is unchanged.

2. **Carriers stranded by zoning.** Buying sheep alone did not solve production:
   seven sheep were purchased but only a few reached pastures because a carrier
   could not leave its assigned zone while work remained there. Livestock PLACE
   tasks now use the existing holder-constrained delivery path, ahead of routine
   work. Emergency tasks with higher priority still take precedence. This lets
   the actual carrier cross zone boundaries to complete the delivery.

3. **Routine priorities undervalued travel.** A worker standing on an animal would
   abandon CARE (priority 65) to walk across the quadrant for WATER (priority 70).
   Routine matching now compares tasks within a 20-point band and charges three
   priority points per movement step, retaining the existing proximity bonus and
   home-zone preferences. Rescue feeding, emergency watering, decay harvesting,
   and animal delivery remain in the preceding dispatch tier.

These changes reuse the existing scheduler and economic planner. They do not
increase the nine-pasture cap, strawberry caps, daily workforce, or purchase
deadline. A 20-animal redesign remains a separate, unproven experiment.

## Controlled diagnostic experiments

Each row uses the same two seeds, 101 and 202, against an inert PASS opponent.
This measures economic throughput without rival market supply; it is not a
competitive win-rate claim. Every match lasted 720 observations and reported
zero emergency fallbacks and no terminal ERROR/INVALID/TIMEOUT status.

| Candidate | Seed 101 | Seed 202 | Mean | Change vs baseline |
|---|---:|---:|---:|---:|
| Unchanged baseline | 66,299 | 71,261 | 68,780.0 | — |
| Daytime reinvestment only | 65,186 | 67,120 | 66,153.0 | −3.8% |
| Reinvestment + carrier delivery | 65,662 | 69,279 | 67,470.5 | −1.9% |
| Reinvestment + delivery + travel-aware routine service | 96,903 | 81,721 | 89,312.0 | **+29.9%** |

The interim candidates were not promoted. Buying animals without the service
improvement consumed cash and worker time without enough additional production.
In seed 101, the final candidate issued 155 CARE actions versus 34 for baseline,
placed nine animals versus two, and issued 286 HARVEST actions versus 242.
These are issued-action counts, not an assertion that every action succeeded.

Raw diagnostics are in `simulations/results/improvement_*_diagnostic.json`.

## Competitive validation

The candidate is evaluated against the frozen baseline on seeds
42, 777, 907, 1234, and 2026, with each seed played in both positions.
These seeds were not used for the two-seed diagnostic changes above.
Results: to be filled after the evaluation completes.

The harness loads a fresh standalone module per player per game and records
artifact hashes, scores, observed daily farm composition, issued actions,
decision timing, and fallback diagnostics. It avoids the unseeded built-in
random opponent used by historical benchmark reports.

## Regression and artifact checks

Four new regression tests were observed failing before implementation. They cover
daytime investment, the deadline/land/cash/hour guards, cross-zone delivery by the
animal holder, and local service selection with emergency preemption.

`python -m pytest agent/tests -q`: **454 passed** (113.89 seconds).

Packaging validation: to be filled after the competitive evaluation completes.

## Reproduction

From the repository root, using the installed Python with kaggle-environments:

```powershell
python scripts/benchmark_improvement.py --candidate submission.py --baseline simulations/results/improvement_baseline_a98e2b3.py --seeds 42 777 907 1234 2026 --both-seats --output simulations/results/improvement_reproduction.json
python -m pytest agent/tests -q
```

The candidate defaults to a temporary bundle built from `agent/` if `--candidate`
is omitted. Scores are final farm cash. Diagnostics and small-sample head-to-head
results do not establish performance against all opponent strategies or current
leaderboard rank.
