# Phase C0: Core Telemetry Correction & Soft Worker Locality Experiment Report

**Date**: September 25, 2026  
**Repository**: [https://github.com/aaryasj0310-stack/farm](https://github.com/aaryasj0310-stack/farm)  
**Branch**: `experiment/sw-forward-architecture-phase-a`  
**Starting Commit**: `a87a308d6fae7a563184fe97195c28c60c9427a0`  
**Production Defaults Preserved**: `SW_FORWARD_ARCHITECTURE_MODE = "OFF"`, `SOFT_WORKER_LOCALITY_MODE = "OFF"`  
**Protected Seeds Preserved**: Tournament seeds `98001–98050` remained strictly untouched.

---

## Executive Summary

Phase C0 addressed the core NW+NE production baseline in two sequential parts:
1. **Part C0-A (Telemetry Correction & Audit)**: Audited and corrected the distorted bottleneck metrics from Phase B1-R3. We proved that B1-R3's reported 64.82% "avoidable movement overhead", 8,968 harvest-ready delays, and 4,034 empty-tile turns were artifacts of hourly polling and naive classification. True grid transit is necessary for farming, but workers were indeed executing an excessive **475.2 quadrant crossings per match** due to rigid, static index-based partitioning.
2. **Part C0-B & C (Soft Worker Locality Implementation & Controlled Experiment)**: Implemented a soft, workload-aware worker locality mechanism with task-continuity protection inside the existing task scheduler (`agent/execution/task_scheduler.py`). Evaluated across **100 paired configurations (200 real-engine matches)** spanning 10 discovery seeds (96501–96510), 5 benchmark opponents, and 2 seats.

### Headline Results

| Metric | CONTROL (`OFF`) | TREATMENT (`ON`) | Paired Difference | Relative Change |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Final Cash** | **$99,788.10** | **$102,591.64** | **+$2,803.54** | **+2.81%** |
| **Median Final Cash Delta** | — | — | **+$2,039.50** | — |
| **Seed-Clustered 95% CI** | — | — | **[+$654.07, +$4,953.01]** | **Statistically Significant** |
| **Win Rate (Pairs > 0)** | — | — | **67 / 100 (67.0%)** | 33 Losses, 0 Ties |
| **Quadrant Crossings / Match** | 469.0 | 382.0 | **-87.0 crossings** | **-18.55%** |
| **Movement Steps / Match** | 4,638.1 | 4,412.1 | **-226.0 moves** | **-4.87%** |
| **Productive Operations / Match** | 2,178.1 | 2,288.8 | **+110.7 ops** | **+5.08%** |
| **Completed Crop Cycles / Match** | 189.4 | 195.5 | **+6.1 crops** | **+3.22%** |
| **Animal Escapes** | 0 | 0 | 0 | **Zero Regressions** |
| **Full Regression Suite** | 1,173 / 1,173 | 1,173 / 1,173 | 0 Failures | **100% Passing** |

---

## PART A — Telemetry Reconciliation & Audit Findings

The Phase B1-R3 audit previously reported:
- Movement actions: 64.82% of worker turns.
- Core empty-tile observations: ~4,034 per match.
- Harvest-ready tile observations: ~8,968 per match.
- Estimated travel opportunity cost: $11,955.

Our authoritative turn-by-turn re-audit across 20 baseline matches (Seeds 96501, 96502 $\times$ 5 benchmark opponents $\times$ 2 seats) uncovered the exact sources of distortion:

### 1. Worker Movement Ledger Distortion
- **B1-R3 Method**: Counted all emitted directional actions (`NORTH`, `SOUTH`, `EAST`, `WEST`) as pure "waste" or "overhead", claiming that removing them would recover $11,955.
- **C0 Authoritative Reality**: In a 10$\times$10 grid, workers must physically walk from the shed/wells to soil tiles. Of the 92,771 executed moves, **85,757 (58.12% of all turns)** were necessary transit to task coordinates, and **7,014 (4.75%)** were necessary transit to shed access tiles.
- **True Inefficiency**: The genuine waste was **cross-quadrant oscillation** (475.2 quadrant crossings per match, ~20–24 per day). Workers frequently crossed paths because unit index $u < \lfloor N/2 \rfloor$ was hard-assigned to NW and $u \ge \lfloor N/2 \rfloor$ to NE, forcing workers to walk across the map even when standing right next to available tasks in the other zone.

### 2. Crop Service & Delays Distortion
- **B1-R3 Method**: Polled tile states every hour (24 times/day). A mature crop waiting 10 hours was counted as 10 "harvest-ready delays"; an unwatered crop at 9 AM was counted 15 times before being watered at 2 PM as 15 "missed waterings".
- **C0 Authoritative Reality**:
  - Discrete crop obligations averaged **187.3 completed cycles per match**.
  - Average harvest wait time was **47.74 hours** (a normal task queue buffer).
  - **Zero crops decayed**, and **zero crops died** from missed watering.
  - Core empty tiles were largely deliberate endgame cash preservation (crops planted after day 26 cannot mature before day 30). In-season replanting gaps averaged only **6.55 hours**.

### 3. Capital & Market Accounting Distortions
- **Hiring Costs**: B1-R3 assumed each hire cost a flat $100. In reality, engine hiring costs follow $\text{mult} \times \text{fib}(n)$ ($1, $1, $2, $3, $5... \times 1), meaning hiring 10 hands costs under $100 total per day, not $1,000+.
- **Seed Purchasing Costs**: B1-R3 valued seed purchases using crop base sale prices (e.g. $250 for melon). In reality, seed catalog prices are $10 for wheat, $20 for carrot, $50 for tomato, $100 for strawberry, and $80 for melon.
- **Order Drops**: Emitted market orders were trimmed by order budget caps, but essential seed and livestock orders executed reliably.

### Summary Reconciliation Table

| Metric | B1-R3 Reported | C0 Corrected Value | Discrepancy Cause | Decision Gate Assessment |
| :--- | :---: | :---: | :--- | :--- |
| **Worker Travel** | 4,782.0 turns (64.8%) | 4,638.6 moves (62.9%) | Necessary geometric transit conflated with waste | **Supported**: 475.2 crossings/match showed substantial cross-quadrant hopping. |
| **Harvest Delays** | 8,968.1 tile-turns | 47.7h mean wait queue | Hourly polling multiplied single events by 24x | Queue buffer existed, but zero crops decayed. |
| **Empty Land** | 4,034.2 tile-turns | 6.55h in-season delay | Endgame non-planting counted as idle waste | Replanting was timely; land wasn't neglected. |
| **Missed Water** | 4,754.2 tile-turns | 0 crop deaths / 0 yield loss | Hourly checks before watering completed | Critical watering was safely maintained. |
| **Hire Costs** | $100 flat / hire | Exact $\text{fib}(n)$ ($1–$21) | Erroneous flat cost assumption | Hires were significantly cheaper than reported. |
| **Seed Spend** | Crop selling price ($250) | Seed catalog price ($80) | Sale price used instead of seed price | Input capital costs were lower than reported. |

---

## PART B — Soft Worker Locality Architecture

### Implementation Details
The soft worker locality mechanism was integrated into `agent/execution/task_scheduler.py` under the explicit experimental switch `SOFT_WORKER_LOCALITY_MODE` (default `"OFF"`).

#### Key Principles
1. **Physical Proximity over Static Partitioning**:
   - Instead of restricting candidates by unit index ($u < N/2$ for NW), candidate evaluation uses the worker's live physical quadrant `u_phys_quad = farm.quadrant_of(pos_by_idx[u])`.
2. **Workload-Conditional Cross-Zone Assistance**:
   - Local tasks incur $0.0$ locality penalty.
   - Remote tasks incur a soft penalty ($10.0$) **unless**:
     - The task is urgent or critical (`prio >= 70`, animal feed, harvest decay, urgent water) $\rightarrow 0.0$ penalty.
     - The worker's current quadrant has exhausted its unassigned task queue (`rem_local_tasks <= 0`) $\rightarrow 0.0$ penalty.
     - The target quadrant has an acute worker deficit (`rem_target_tasks > free_in_target`) $\rightarrow$ reduced $3.0$ penalty.
3. **Task-Continuity Protection**:
   - If a worker is actively traveling toward a valid target (`u in _ACTIVE_MISSIONS`), it receives a $+6.0$ continuity bonus, preventing turn-by-turn routing jitter and abandoned journeys.
4. **Hard Safety Guarantees**:
   - Emergency feeding, near-deadline watering, and mature product collection preserve their elevated priority scoring, completely overriding locality preferences.
5. **Exact Control Baseline Preservation**:
   - When `SOFT_WORKER_LOCALITY_MODE == "OFF"`, the exact legacy C2/C6 zonal dispatch and static index partitioning execute unchanged.

---

## PART C — Controlled Discovery Experiment Analysis

### Matrix Specifications
- **Discovery Seeds**: 10 seeds (96501, 96502, 96503, 96504, 96505, 96506, 96507, 96508, 96509, 96510)
- **Opponents**: 5 benchmarks (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`)
- **Seats**: 2 seats (0 and 1)
- **Total Configurations**: 100 paired configurations = **200 real-engine matches**

### Financial Performance Distribution
- **Mean Paired Cash Delta**: **+$2,803.54**
- **Median Paired Cash Delta**: **+$2,039.50**
- **Seed-Clustered 95% Confidence Interval**: **[+$654.07, +$4,953.01]**
- **Win Rate**: **67.0%** (67 wins, 33 losses, 0 ties)
- **Percentiles**:
  - $P_{10}$: -$5,376.00
  - $P_{25}$: -$1,059.00
  - $P_{50}$: +$2,039.50
  - $P_{75}$: +$8,481.00
  - $P_{90}$: +$12,006.00
- **Worst Paired Regression**: -$13,096.00 (Seed 96508 vs `full_production_agent` Seat 0)
- **Best Paired Gain**: +$21,417.00 (Seed 96502 vs `cow_milk_engine` Seat 0)

### Breakdown by Opponent

| Opponent | Control Mean Cash | Treatment Mean Cash | Paired Delta | Positive Pairs |
| :--- | :---: | :---: | :---: | :---: |
| `cow_milk_engine` | $99,284.10 | $103,415.25 | **+$4,131.15** | 16 / 20 (80.0%) |
| `pass` | $100,601.70 | $103,297.80 | **+$2,696.10** | 16 / 20 (80.0%) |
| `pure_wheat_rush` | $99,754.40 | $102,361.55 | **+$2,607.15** | 14 / 20 (70.0%) |
| `full_production_agent` | $99,720.80 | $102,191.05 | **+$2,470.25** | 11 / 20 (55.0%) |
| `melon_sniper` | $99,579.50 | $101,692.55 | **+$2,113.05** | 10 / 20 (50.0%) |

*Every benchmark opponent exhibited a solid positive mean delta between +$2,113 and +$4,131.*

### Breakdown by Seat

| Seat | Control Mean Cash | Treatment Mean Cash | Paired Delta |
| :---: | :---: | :---: | :---: |
| **Seat 0** | $99,697.10 | $102,427.60 | **+$2,730.50** |
| **Seat 1** | $99,879.10 | $102,755.68 | **+$2,876.58** |

*Seat symmetry is exceptional; performance gain is independent of player turn order.*

### Breakdown by Seed (10 Seeds $\times$ 10 Matches Each)

| Seed | Mean Control Cash | Mean Treatment Cash | Mean Paired Delta | Positive Pairs |
| :---: | :---: | :---: | :---: | :---: |
| **96501** | $95,739.50 | $97,791.10 | **+$2,051.60** | 6 / 10 |
| **96502** | $103,149.40 | $110,682.60 | **+$7,533.20** | 7 / 10 |
| **96503** | $96,076.00 | $95,295.50 | **-$780.50** | 4 / 10 |
| **96504** | $97,949.70 | $99,774.00 | **+$1,824.30** | 7 / 10 |
| **96505** | $100,539.10 | $105,933.50 | **+$5,394.40** | 8 / 10 |
| **96506** | $101,605.60 | $100,386.60 | **-$1,219.00** | 5 / 10 |
| **96507** | $101,529.80 | $103,679.10 | **+$2,149.30** | 7 / 10 |
| **96508** | $100,428.10 | $103,624.20 | **+$3,196.10** | 8 / 10 |
| **96509** | $98,397.70 | $105,378.50 | **+$6,980.80** | 9 / 10 |
| **96510** | $102,471.70 | $103,376.90 | **+$905.20** | 6 / 10 |

*8 out of 10 discovery seeds demonstrated positive mean paired returns.*

---

## PART D — Operational Mechanism & Causal Attribution

### Did Movement Reduction Translate into Productive Output?
Yes. The causal chain is clearly visible in the empirical data:
1. **Quadrant Crossings**: Reduced from **469.0 down to 382.0 per match** (-87.0 crossings, -18.55%). Workers stopped pointlessly traversing between NW and NE when nearby tasks were waiting.
2. **Movement Turns**: Reduced from **4,638.1 down to 4,412.1 moves per match** (-226.0 moves, -4.87%).
3. **Productive Operations Executed**: Increased from **2,178.1 up to 2,288.8 ops per match** (+110.7 ops, +5.08%).
4. **Crop Yield & Realization**: Completed crop cycles increased from **189.4 to 195.5 per match** (+6.1 cycles).
5. **Final Cash**: Converted into **+$2,803.54** higher average terminal cash.

### Safety Invariants
- **Livestock Feeding**: 100% successful in both Control and Treatment. **Zero animal escapes** occurred across all 200 matches.
- **Urgent Watering**: Priority override ensured zero crops died of dehydration in either policy.
- **Crop Decay**: Zero crops decayed before harvest.
- **Shed Access**: Full access maintained; zero worker deadlocks.

---

## PART E — Verification & Package Integrity

1. **Targeted Unit Tests**:
   - `agent/tests/test_soft_worker_locality.py`: 10/10 passed.
   - `agent/tests/test_adaptive_zonal_dispatch.py`: 12/12 passed.
2. **Full Regression Suite**:
   - `pytest agent/tests`: **1,173 passed, 0 failed, 0 skipped** in 165.13s.
3. **Submission Package Parity**:
   - Synchronized via `scripts/build_submission.py`.
   - Verified 1:1 parity across all 44 runtime modules.
   - Official zip built: `dist/submission.zip` (325,800 bytes).
   - Clean-room isolated 720-step execution completed successfully ($104,130 reward).
4. **Configuration Safety**:
   - `agent/config.py`: `SOFT_WORKER_LOCALITY_MODE = "OFF"` (production default preserved).
   - `agent/config.py`: `SW_FORWARD_ARCHITECTURE_MODE = "OFF"` (production default preserved).

---

## PART F — Strategic Recommendations & Next Steps

1. **Phase C0 Result**: Soft Worker Locality is a verified positive improvement on the discovery panel (+**$2,803.54** mean paired cash delta, seed-clustered 95% CI $[+\$654, +\$4,953]$).
2. **Production Precaution**: In accordance with the Phase C0 instructions, soft worker locality remains `OFF` by default in production.
3. **Recommended Next Step**:
   - Before promoting soft worker locality to the default production configuration, evaluate it on a fresh, non-protected validation panel (e.g. Seeds 97001–97010) to confirm generalization beyond the consumed discovery seeds.
   - Once confirmed, soft worker locality can serve as the new high-efficiency core baseline (~$102.6k average cash) from which subsequent SW-forward or capital-allocation improvements are designed.
