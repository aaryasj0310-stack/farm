# SW P1.1 Responsive Scheduler — Balanced Three-Arm Results

**Status:** causal improvement confirmed, **not production-ready**.

## Exact runtimes

- Control: `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- P1 purchase-only: `b89c8381b341d43c9e81e0701fd8d39edbc8aaaa`
- P1.1 scheduler-only treatment: `b44a1d2f754bc6ecb66077033a2bf44350146bab`
- Engine: `kaggriculture 1.32.7`
- Design: 20 deterministic seed/opponent scenarios × both player seats = **40 matched cases per arm / 120 complete games**
- Experiment errors: **0**
- SW incremental land price: **$2,000**

P1.1 keeps the P1 purchase correction active and changes only post-purchase scheduler home-zone allocation. MacroPlanner SW activation is intentionally unchanged.

## Validation

Before the economic run:

- Focused scheduler/P1 tests: **34 passed**
- Full agent regression suite: **1,005 passed**
- Source/submission parity: passed
- Canonical build: passed; 35 runtime modules synchronized
- Isolated 720-turn validation: completed successfully, P0 **$102,622**, P1 $0

The isolated score is a package/correctness check, not A/B evidence.

## Aggregate economic result

| Metric | Control | P1 | P1.1 |
| --- | ---: | ---: | ---: |
| Mean score | **$101,387.13** | $81,542.73 | **$92,596.58** |
| Confirmed SW acquisitions | 0 / 40 | 32 / 40 | 31 / 40 |
| Starvation observations | **435** | 1,137 | **1,447** |
| NW+NE unwatered EOD observations | **5,560** | 8,578 | **7,721** |
| NW+NE harvest executions | **10,399** | 8,150 | **9,290** |
| NW+NE productive operations | **80,531** | 63,879 | **73,065** |
| Travel distance | **176,357** | 189,635 | **179,945** |
| Seed spend | $189,770 | $216,020 | $210,180 |
| Wheat buy units | 34,133 | 30,176 | 42,158 |
| Negative-cash observations | 0 | 0 | 0 |

### Matched score deltas

- **P1 − Control:** mean **−$19,844.40**, median −$21,953; 95% CI **[−$23,998.54, −$15,690.26]**; 0W / 8T / 32L.
- **P1.1 − Control:** mean **−$8,790.55**, median −$9,553.50; 95% CI **[−$11,891.45, −$5,689.65]**; 6W / 0T / 34L.
- **P1.1 − P1:** mean **+$11,053.85**, median +$12,034; 95% CI **[+$6,000.81, +$16,106.89]**; 31W / 0T / 9L.

The scheduler-only repair therefore recovers about **56% of P1's average score damage**, but still leaves a large, statistically clear deficit versus Control.

## Causal scheduler findings

Relative to P1, P1.1:

- raises NW+NE harvest executions by **14.0%**;
- raises NW+NE productive operations by **14.4%**;
- reduces NW+NE unwatered observations by **10.0%**;
- reduces scheduler travel distance by **5.1%**;
- reduces mean score loss by **$11,053.85**.

This is strong evidence that rigid Rule W1 worker partitioning was a **major causal contributor** to the P1 collapse.

P1.1 retains **89.3%** of Control NW+NE harvest executions versus only **78.4%** under P1. It still fails the desired ~95% core-harvest retention target.

## Remaining safety failure

P1.1 is not safe enough to promote.

Starvation rises to **1,447 observations**, compared with:

- Control: 435
- P1: 1,137

So starvation is **+233% versus Control** and **+27% versus P1**, even though crop labor and travel improve.

NW+NE unwatered observations also remain **38.9% above Control**.

This means the static SW squad was not the only defect. The unchanged SW activation/crop workload still creates more total work than the farm can safely absorb, and/or the responsive allocation's core workload estimate does not protect feed execution strongly enough. The next experiment must distinguish those mechanisms rather than relaxing purchase gates further.

## Per-opponent score result

| Opponent | Control mean | P1 mean | P1.1 mean | P1.1 − Control | P1.1 − P1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| pass | $102,187.00 | $78,111.00 | $96,676.13 | −$5,510.88 | +$18,565.13 |
| pure_wheat_rush | $101,286.75 | $79,115.25 | $96,505.63 | −$4,781.13 | +$17,390.38 |
| cow_milk_engine | $102,248.38 | $76,772.38 | $93,712.63 | −$8,535.75 | +$16,940.25 |
| melon_sniper | $100,155.63 | $84,364.88 | $88,394.75 | −$11,760.88 | +$4,029.88 |
| full_production_agent | $101,057.88 | $89,350.13 | $87,693.75 | −$13,364.13 | **−$1,656.38** |

P1.1 remains below Control in every opponent group and is slightly worse than P1 against `full_production_agent`.

## Scheduler telemetry caveat

The exact Control and P1 SHAs predate the newly added `home_unit_turns` and `sw_anchor_assignments` counters. Their raw zero values in the first generated JSON were **not measured zeros**.

Those legacy summary fields are now marked `null` in the structured artifact and must not be used for cross-arm comparison.

P1.1 itself recorded **20,404 SW home-unit turns** and **0 SW anchor assignments**. The zero anchor count is directly measured for P1.1 and is consistent with the workload-responsive allocator removing the old idle SW anchoring behavior.

## Interpretation

The experiment supports:

> **Rigid SW worker partitioning is a major real defect, but fixing it alone does not make early SW acquisition profitable or safe.**

The score gap shrinks substantially, core harvests recover, and travel falls. However, the treatment still loses **$8.8k per game on average** versus production, misses ~10.7% of Control NW+NE harvest executions, and worsens starvation.

Therefore:

- **Do not merge P1.1 into production.**
- Keep P2 seed-payback changes out of this arm.
- Do not relax the SW purchase gate further.
- Do not redesign crop portfolio yet.

## Next isolated experiment

The next treatment should be:

**P1 purchase correction + responsive scheduler + serviceability-aware SW activation**

while keeping all other strategy unchanged.

The purpose is to test the second confirmed architecture defect: MacroPlanner currently discards `is_serviceable` and activates `best_k` SW tiles anyway.

That next arm should make SW planting/activation conditional on an explicit serviceability result and should preserve feed-execution capacity as a hard invariant. It must be compared against all three existing arms, with the same balanced-seat design.

Do not merge any SW treatment until it reaches Control-level safety and economic performance on a larger held-out validation set.
