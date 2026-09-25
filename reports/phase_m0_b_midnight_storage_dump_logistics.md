# Phase M0-B: Engine Mechanics Exploitation — Midnight Storage Dump Logistics Report

## Executive Summary

Phase M0-B evaluated whether the Kaggriculture engine's automated midnight inventory transfer (`_drop_inventories_to_shed`) could be harnessed as an ephemeral buffer to relieve shed congestion and mitigate the negative tail observed in Phase M0-A (where accelerated crop pipelining caused premature shed fill and delayed planned livestock purchases).

The investigation proceeded across:
1. **Engine Micro-Tests (Part A):** Executed 6 rigorous micro-tests directly against the unmodified Kaggriculture engine (`scripts/verify_midnight_storage_dump.py`). Confirmed that worker inventories automatically dump into the shed at the transition from Hour 23 to Hour 0 regardless of worker position or current action. **Crucially, discovered that any inventory exceeding the 100-item shed capacity is silently discarded and destroyed by the engine.** Furthermore, confirmed that market orders can only fulfill from the shed, meaning goods held on workers cannot be sold on the same day.
2. **M0-A Forensic Recheck (Part B):** Categorized all 39 losing pairs from Phase M0-A. Confirmed that 14 pairs (35.9%) were directly driven by shed congestion and delayed livestock purchases.
3. **Architecture & Guarded Buffering (Parts C–E):** Implemented `MIDNIGHT_STORAGE_DUMP_MODE` (default `"OFF"`) and `MidnightStorageController` with strict headroom gating (`projected_shed <= 95`), item filtering (only non-perishable harvest crops), and late-day activation (`hour >= 18`).
4. **Controlled 4-Arm Discovery Experiment (Parts G–J):** Evaluated all 4 factorial combinations across the 10 fresh discovery seeds (96511–96520) $\times$ 5 benchmark opponents $\times$ 2 seats = 100 scenario cells (400 real-engine matches):
   - **Arm A0B0 (Control):** Baseline NW+NE production.
   - **Arm A1B0 (M0-A Pipeline):** Same-turn crop pipelining alone.
   - **Arm A0B1 (M0-B Storage Dump):** Midnight storage buffering alone.
   - **Arm A1B1 (Combined Package):** Both crop pipelining and midnight buffering active.

### Key Quantitative Findings:
- **Baseline Cash (A0B0):** \$103,689.81
- **M0-A Standalone Effect (A1B0 - A0B0):** Mean = **+\$287.37**, Median = **-\$188.00**, Win Rate = 49.0% (49W / 51L), 95% CI = `[-$1,974.38, +$2,549.12]`.
- **M0-B Standalone Effect (A0B1 - A0B0):** Mean = **-\$95.51**, Median = **+\$188.00**, Win Rate = 53.0% (53W / 47L), 95% CI = `[-$1,879.76, +$1,688.74]`.
- **Combined Package Effect (A1B1 - A0B0):** Mean = **-\$241.50**, Median = **-\$855.00**, Win Rate = 42.0% (42W / 58L), 95% CI = `[-$1,933.88, +$1,450.88]`.
- **Incremental M0-B Effect (A1B1 - A1B0):** Mean = **-\$528.87**, Median = **-\$73.00**, Win Rate = 39.0% (39W / 3T / 58L), 95% CI = `[-$1,596.78, +$539.04]`.
- **Interaction Synergy:** Mean = **-\$433.36** (negative synergy between features).
- **M0-A Negative Tail Rescue:** Rescued 9 of 51 M0-A losses (17.6% rescue rate), but worsened 21 existing losses and created 16 new losses.
- **Root Cause of Underperformance:** While worker holding eliminates midday deposit trips, it traps harvested goods on workers during the late-day market settlement window (Hours 18–23). Delaying sales until the next day depresses daily cash velocity, hindering timely evening capital purchases and compounding over the 30-day season.

**Verdict:** **M0-B is economically unviable as a general storage buffer and is REJECTED from advancing to fresh confirmation.**

---

## Part A: Engine Micro-Test Verdict

The micro-test suite (`scripts/verify_midnight_storage_dump.py`) executed 6 exhaustive tests against the official Kaggriculture engine. All tests PASSED (100% verification rate). Artifacts are preserved in `simulations/results/phase_m0_b_engine_verification/`.

### 1. Day Boundary Auto-Dump
- **Engine Logic:** In `kaggriculture.py`, step execution checks `(step + 1) % 24 == 0` (transition from Hour 23 to Hour 0). When true, `_drop_inventories_to_shed(private, shed_cap)` iterates over all units and moves items from `unit['inventory']` into `private['shed']`.
- **Micro-Test Confirmation:** Verified across 10 trials. A worker holding 5 wheat units at Step 23 (Hour 23) has worker inventory cleared to 0 at Step 24 (Day 1, Hour 0), with the 5 wheat units appearing in `private['shed']`.

### 2. Overflow and Discard Behavior (Critical Vulnerability)
- **Engine Logic:** `_drop_inventories_to_shed` transfers items only up to `shed_cap` (100). Any excess items remaining after the shed reaches 100 are **silently discarded and permanently destroyed**.
- **Micro-Test Confirmation:** Verified. With 95 items in the shed and workers carrying 10 items (total 105), the shed filled to exactly 100 items at midnight, and the remaining 5 items were permanently lost from the environment.
- **Architectural Implication:** Any buffering controller must enforce a strict dynamic safety ceiling ($S_{\text{current}} + \sum W_{\text{carried}} \le 95$) to prevent catastrophic inventory loss.

### 3. Item Type Universality
- **Micro-Test Confirmation:** Tested all item categories: crops (`WHEAT`, `CARROT`, `MELON`), animal products (`MILK`, `EGG`, `WOOL`), raw materials, and fertilizer. All item types are transferred to the shed uniformly.

### 4. Worker Carry Limits and Action Concurrency
- **Micro-Test Confirmation:** Workers have no intrinsic carry limit (tested carrying > 50 units). Furthermore, workers carrying items can simultaneously execute standard movement, harvesting, or watering without movement penalties or action blocks.

### 5. Market Execution Semantics
- **Micro-Test Confirmation:** Confirmed that market sell orders (`market.process_orders`) resolve exclusively against `private['shed']`. Items resting in worker inventories are completely invisible to the market and cannot fulfill sell orders during evening hours.

### 6. Pre-Midnight Action Ordering
- **Micro-Test Confirmation:** Actions in Hour 23 (e.g., harvesting) populate the worker inventory during Step 23. The end-of-step rollover immediately transfers the items to the shed at Step 24 (Day+1 Hour 0), making them available for early morning trading.

---

## Part B: M0-A Forensic Recheck

A forensic re-analysis of the 39 losing pairs from Phase M0-A was conducted to determine the exact failure modes:
- **Category A (Shed Congestion & Delayed Capital Purchases):** 14 pairs (35.9%). Faster crop harvesting filled the shed earlier in the day, reaching $\ge 95$ capacity during key capital purchase windows and delaying planned livestock acquisitions (e.g., Sheep/Cows).
- **Category B (Market Timing & Price Depression):** 13 pairs (33.3%). Accelerated crop sales coincided with opponent market gluts or lower spot prices.
- **Category C (Worker Opportunity Cost):** 12 pairs (30.8%). Workers committed to pipelining were diverted from peripheral watering or livestock maintenance.

This confirmed the hypothesis that shed congestion was indeed the single largest operational friction point of M0-A, justifying the evaluation of M0-B.

---

## Part C–E: Architecture & Implementation

### 1. Configuration Isolation (`agent/config.py`)
```python
MIDNIGHT_STORAGE_DUMP_MODE = "OFF"  # "OFF" or "ON"
```
Production defaults remain strictly:
```python
SW_FORWARD_ARCHITECTURE_MODE = "OFF"
SOFT_WORKER_LOCALITY_MODE = "OFF"
SAME_TURN_CROP_PIPELINE_MODE = "OFF"
MIDNIGHT_STORAGE_DUMP_MODE = "OFF"
```

### 2. Midnight Storage Controller (`agent/execution/midnight_storage_controller.py`)
Encapsulates safe buffering logistics:
1. **Late-Day Window:** Only activates at `hour >= 18` (Day steps 18–23).
2. **Strict Headroom Ceiling:**
   $$\text{Current Shed} + \text{Carried Inventory} + \text{New Harvest} \le 95$$
   If this limit is exceeded, workers are forced to deposit immediately.
3. **Safe Item Whitelist:** Buffering is restricted to non-perishable harvest crops (`WHEAT`, `CARROT`, `MELON`). Vital feeds and high-value animal products are never buffered.
4. **Deposit Trip Suppression:** Signals `task_scheduler.py` to bypass `deposit_product` tasks when buffering conditions are met, saving travel turns.

### 3. Market Brain Pre-Midnight Relief (`agent/market/market_brain.py`)
At `hour >= 18`, if shed occupancy exceeds 75 units, market sell volumes are proactively cleared to ensure ample headroom for midnight arrival.

---

## Part F: Unit Tests & Security Verification

1. **Targeted Unit Tests:** `agent/tests/test_midnight_storage_dump.py` covers all 10 specifications (configuration defaults, late-day gating, headroom enforcement, item filtering, safe deposit bypass, reset idempotency, and baseline parity). All 10 passed.
2. **Full Test Suite:** 1,195 passed out of 1,195 tests in 154.15s (0 failures, 0 errors, 0 skips).
3. **Snyk SAST Scan:** Completed with **0 open issues** (0 High, 0 Medium, 0 Low).
4. **Isolated Package Validation:** Synchronized `submission/` (46 runtime modules), built `dist/submission.zip` (332,242 bytes), and verified in an isolated environment with a full 720-step live match ($P_0=\$96,569.00, P_1=\$0.00$).

---

## Part G–J: Controlled 4-Arm Discovery Experiment Results

The experiment evaluated 100 scenario cells (10 discovery seeds 96511–96520 $\times$ 5 benchmark opponents $\times$ 2 seats) across all 4 factorial arms (400 real-engine matches).

### 1. Final Cash Distributions

| Arm | Mode Configuration | Mean Cash | Median Cash | Min Cash | Max Cash |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **A0B0** | Control (Both OFF) | \$103,689.81 | \$104,210.00 | \$84,579.00 | \$124,325.00 |
| **A1B0** | M0-A Pipeline Alone | \$103,977.18 | \$104,022.00 | \$81,978.00 | \$124,895.00 |
| **A0B1** | M0-B Dump Alone | \$103,594.30 | \$104,398.00 | \$70,061.00 | \$124,808.00 |
| **A1B1** | Combined Package | \$103,448.31 | \$103,355.00 | \$77,172.00 | \$126,313.00 |

### 2. Paired Delta Analysis & Statistical Significance

| Comparison | Contrast | Mean Delta | Median Delta | Win / Tie / Loss | Win Rate | Seed-Clustered 95% CI |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **M0-A Effect** | $A_1B_0 - A_0B_0$ | **+\$287.37** | -\$188.00 | 49 / 0 / 51 | 49.0% | `[-$1,974.38, +$2,549.12]` |
| **M0-B Standalone** | $A_0B_1 - A_0B_0$ | **-\$95.51** | +\$188.00 | 53 / 0 / 47 | 53.0% | `[-$1,879.76, +$1,688.74]` |
| **Package Effect** | $A_1B_1 - A_0B_0$ | **-\$241.50** | -\$855.00 | 42 / 0 / 58 | 42.0% | `[-$1,933.88, +$1,450.88]` |
| **Incremental M0-B** | $A_1B_1 - A_1B_0$ | **-\$528.87** | -\$73.00 | 39 / 3 / 58 | 39.0% | `[-$1,596.78, +$539.04]` |
| **Interaction Term** | $\Delta_{\text{combo}} - (\Delta_A + \Delta_B)$ | **-\$433.36** | -\$312.00 | 45 / 0 / 55 | 45.0% | `[-$2,655.47, +$1,788.75]` |

### 3. Percentile & Tail Breakdown

| Metric | A0B0 (Control) | A1B0 (M0-A) | A0B1 (M0-B) | A1B1 (Combo) |
| :--- | :---: | :---: | :---: | :---: |
| **P10 Delta vs Control** | \$0.00 | -\$6,534.00 | -\$6,827.00 | -\$8,488.00 |
| **P25 Delta vs Control** | \$0.00 | -\$4,074.00 | -\$3,218.00 | -\$3,852.00 |
| **P50 Delta vs Control** | \$0.00 | -\$188.00 | +\$188.00 | -\$855.00 |
| **Worst Negative Pair** | \$0.00 | -\$22,063.00 | -\$16,582.00 | -\$15,465.00 |
| **Best Positive Pair** | \$0.00 | +\$23,090.00 | +\$22,126.00 | +\$23,040.00 |

### 4. Storage & Logistics Telemetry

| Telemetry Metric | A0B0 | A1B0 | A0B1 | A1B1 |
| :--- | :---: | :---: | :---: | :---: |
| **Turns Shed $\ge 90$ Items** | 1,397 | 1,453 | 1,363 | 1,516 |
| **Turns Shed $\ge 95$ Items** | 935 | 963 | 915 | 1,000 |
| **Turns at Capacity (100 Items)** | 477 | 525 | 521 | 558 |
| **Items Lost to Midnight Overflow** | 0 | 0 | 0 | 0 |
| **Avg Worker Holds per Match** | 0.00 | 0.00 | 277.89 | 269.09 |
| **Avg Items Buffered per Match** | 0.00 | 0.00 | 1,243.86 | 1,210.81 |

### 5. Capital Purchases & M0-A Loss Forensics
- **Purchases per Match:** A0B0: 7.41, A1B0: 7.77, A0B1: 7.83, A1B1: 8.10.
- **M0-A Negative Pairs Rescued:** Across the 51 losing cells in A1B0, enabling M0-B (A1B1) rescued **9 cells into wins** (17.6% rescue rate) and reduced losses in 18 cells. However, it caused worse losses in 21 cells and introduced 16 new losses in previously winning cells.
- **Root Cause of Failure:** By withholding goods on workers between Hours 18 and 23, the farm missed the evening trading session. Consequently, cash from those crops was credited 1 turn after midnight rather than before the end-of-day livestock purchase window. This liquidity trap negated the travel time savings.

---

## Part K: Safety Validation

| Safety Indicator | A0B0 | A1B0 | A0B1 | A1B1 |
| :--- | :---: | :---: | :---: | :---: |
| **Animal Escapes** | 0 | 0 | 0 | 0 |
| **Max Consecutive Unfed Turns** | 1 | 1 | 1 | 1 |
| **Starvation Events** | 0 | 0 | 0 | 0 |
| **Inventory Lost to Overflow** | 0 | 0 | 0 | 0 |
| **Urgent Task Preemption** | 0 | 0 | 0 | 0 |

The safety architecture functioned flawlessly: zero animals escaped, no inventory was destroyed by capacity overflow, and critical feeding and watering were never compromised.

---

## Part L: Comprehensive Decision Gate Answers

### 1. Does automatic worker inventory dumping at midnight genuinely exist?
**YES.** Verified with 100% fidelity in both micro-tests and match simulations. At step `(step + 1) % 24 == 0`, the engine executes `_drop_inventories_to_shed(private, shed_cap)`.

### 2. What is the exact engine timing/order?
The dump occurs in the environment's `step()` method at the very end of Hour 23, after all agent worker actions for Step 23 are processed, and immediately before observation generation for Step 24 (Day+1, Hour 0).

### 3. Does worker position matter?
**NO.** The engine transfers items from `unit['inventory']` to `private['shed']` for all units globally, regardless of their `(r, c)` position, proximity to the shed, or current task.

### 4. What happens when shed capacity is insufficient?
**CRITICAL SILENT DISCARD.** If `shed_occupancy + worker_inventory > 100`, the engine fills the shed to 100 and **permanently deletes** the excess items without raising an error.

### 5. Which item types can safely use the mechanic?
Only non-perishable harvest crops (`WHEAT`, `CARROT`, `MELON`) that are not scheduled for immediate evening sale. Animal feed, animals, and products needed for evening trading cannot be safely buffered.

### 6. How much temporary effective storage can workers provide?
Up to 50+ items per worker theoretically, but bounded by the shed's remaining headroom ($\le 95$ items) to prevent discard at midnight.

### 7. What is the worker/task opportunity cost?
Holding items on workers incurs zero movement penalty, but locks those items out of the market order fulfillment engine until Day+1 Hour 0.

### 8. Was the M0-A tail actually caused primarily by shed/logistics congestion?
**PARTIALLY (35.9%).** 14 of 39 losing pairs in M0-A were caused by shed congestion delaying capital purchases, while the remaining 64.1% stemmed from market price timing (33.3%) and worker opportunity costs (30.8%).

### 9. How much does M0-B reduce shed congestion standalone?
Standalone M0-B reduced turns at $\ge 90$ items slightly from 1,397 to 1,363 (-2.4%), but actually increased turns at full capacity (100 items) from 477 to 521 (+9.2%) due to the midnight dump surge.

### 10. How much does M0-B reduce shed congestion with M0-A active?
**IT DOES NOT REDUCE CONGESTION; IT INCREASES IT.** In A1B1, turns at $\ge 90$ items rose to 1,516 (vs 1,453 in A1B0), and turns at full capacity rose to 558 (vs 525 in A1B0), because the combined crop acceleration overwhelmed the shed every midnight.

### 11. What is the A0B1 - A0B0 cash effect?
Mean delta = **-\$95.51** (Median: **+\$188.00**, Win Rate: 53.0%, 95% CI: `[-$1,879.76, +$1,688.74]`).

### 12. What is the A1B1 - A1B0 cash effect?
Mean delta = **-\$528.87** (Median: **-\$73.00**, Win Rate: 39.0%, 95% CI: `[-$1,596.78, +$539.04]`).

### 13. What is the A1B1 - A0B0 total package effect?
Mean delta = **-\$241.50** (Median: **-\$855.00**, Win Rate: 42.0%, 95% CI: `[-$1,933.88, +$1,450.88]`).

### 14. What is the interaction/synergy term?
Mean interaction = **-\$433.36** (95% CI: `[-$2,655.47, +$1,788.75]`). The two features exhibit negative interaction.

### 15. Does M0-B recover delayed livestock/capital purchases?
**NO.** Average capital purchases per match changed negligibly (7.77 in A1B0 vs 8.10 in A1B1), but the timing of cash inflows was delayed past critical evening purchase cutoffs.

### 16. Does P10 improve?
**NO.** P10 delta worsened from -\$6,534.00 (A1B0) to **-\$8,488.00** (A1B1).

### 17. Does P25 improve?
**SLIGHTLY.** P25 delta improved slightly from -\$4,074.00 (A1B0) to **-\$3,852.00** (A1B1), but remained deeply negative.

### 18. Does the worst M0-A regression improve?
**YES.** The worst pair regression improved from -\$22,063.00 (A1B0) to **-\$15,465.00** (A1B1).

### 19. How many of M0-A's negative pairs are rescued?
**9 out of 51 losing cells (17.6%)** were rescued to wins, but 21 losses became worse and 16 new losses were introduced.

### 20. Does M0-B introduce any new safety or worker-utilization failures?
**NO.** Safety metrics remained perfect (0 escapes, 0 starved animals, 0 items lost to overflow).

### 21. What is the seed-clustered 95% CI for the combined package?
**`[-$1,933.88, +$1,450.88]`** ($t=2.262, \text{df}=9$). The interval spans zero and has a negative center (-\$241.50).

### 22. Final Recommendation
**M0-B MUST BE REJECTED.** 
While the underlying mechanic is genuine, worker buffering delays revenue realization past evening market hours, reducing liquidity for end-of-day investments and exacerbating midnight shed capacity pressure. M0-B must not advance to fresh confirmation. Both M0-A and M0-B remain OFF in production.

---

## Part M: Artifact Index

All experiment raw data and analysis structures are preserved in:
- `simulations/results/phase_m0_b_engine_verification/`
  - `manifest.json`: Verification run metadata and pass/fail summary.
  - `midnight_dump_tests.json`: Day boundary transfer observations.
  - `capacity_tests.json`: Overflow and silent discard telemetry.
  - `inventory_type_tests.json`: Crop and animal item type verification.
  - `action_order_tests.json`: Timing and task concurrency traces.
  - `engine_trace.json`: Turn-by-turn state transitions.
- `simulations/results/phase_m0_b_discovery/`
  - `manifest.json`: 400-match experiment metadata and configuration.
  - `matched_results.json`: Full 100-cell matched cash deltas and action logs.
  - `aggregate_tables.json`: Statistical distributions, quantiles, and clustered CIs.
  - `storage_telemetry.json`: Shed capacity and worker hold metrics across all arms.
  - `capital_purchase_timing.json`: Timing and count of capital investments.
  - `safety_comparison.json`: Escape, feeding, and starvation audits.
  - `interaction_analysis.json`: Factorial interaction terms and rescue rates.
  - `losing_pair_forensics.json`: Detailed divergence traces for regressed matches.
  - `representative_traces.json`: Concrete step-by-step telemetry of key divergence points.

---

## Experimental Discipline & Stop Condition

In strict accordance with the experimental protocol:
1. All production flags remain disabled:
   ```python
   SW_FORWARD_ARCHITECTURE_MODE = "OFF"
   SOFT_WORKER_LOCALITY_MODE = "OFF"
   SAME_TURN_CROP_PIPELINE_MODE = "OFF"
   MIDNIGHT_STORAGE_DUMP_MODE = "OFF"
   ```
2. Reserved fresh-confirmation seeds (`96521–96540`) and protected tournament seeds (`98001–98050`) remain **completely untouched**.
3. No code has been merged to `main`.
4. Execution stops here as directed.
