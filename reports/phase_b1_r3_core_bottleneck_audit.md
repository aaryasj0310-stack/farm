# Phase B1-R3: SW Evidence Closure & Core-Farm Bottleneck Audit Report

## Executive Summary

Phase B1-R3 successfully achieves two sequential objectives on branch `experiment/sw-forward-architecture-phase-a`:
1. **Task A (SW Experimental Integrity)**: Formally reproduces the corrected SW purchase-retry state machine inside the live Kaggle simulation engine ([`kaggriculture.py`](file:///C:/Users/rohit/AppData/Local/Programs/Python/Python312/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py)) from dynamic observation events without hardcoded outcomes. The trace proves that initial budget drops (due to the $300 cash reserve) no longer cause permanent lockup, and retries execute cleanly once liquidity is restored.
2. **Task B (Core-Farm Bottleneck Audit)**: Establishes a rigorous, engine-grounded performance ledger across a 20-match panel of the current production baseline (`SW_FORWARD_ARCHITECTURE_MODE = "OFF"`). Across all 5 benchmark opponents and both seats, the baseline achieves a mean final cash of **$99,444.45**, leaving a **$30,555.55 gap** to the $130,000 target. The primary bottleneck is **Worker Travel Overhead (64.82% of worker turns spent walking)**, followed by **Core Tile Idleness (4,034.2 tile-turns/match)** and **Harvest Delays (8,968.1 tile-turns/match)**.

---

## Part A: SW Purchase-Retry Engine Verification

### 1. Reproducible Diagnostic Setup
- **Diagnostic Script**: [`scripts/verify_sw_purchase_retry_engine.py`](file:///d:/website%20project/kaggri%20ox/scripts/verify_sw_purchase_retry_engine.py)
- **Reproduction Command**: `python scripts/verify_sw_purchase_retry_engine.py`
- **Evaluated Commit SHA**: `709c6def9d8052a7598be0fbd375e6faf25b4913`
- **Engine Version**: `kaggle_environments 1.32.7`
- **Configuration**: Seed `96502`, Opponent `pure_wheat_rush`, Seat `0`, Mode `TREATMENT`.
- **Telemetry Storage**:
  - [`simulations/results/phase_b1_r3_retry/manifest.json`](file:///d:/website%20project/kaggri%20ox/simulations/results/phase_b1_r3_retry/manifest.json)
  - [`simulations/results/phase_b1_r3_retry/raw_engine_trace.json`](file:///d:/website%20project/kaggri%20ox/simulations/results/phase_b1_r3_retry/raw_engine_trace.json)
  - [`simulations/results/phase_b1_r3_retry/derived_event_summary.json`](file:///d:/website%20project/kaggri%20ox/simulations/results/phase_b1_r3_retry/derived_event_summary.json)
  - [`simulations/results/phase_b1_r3_retry/verification_report.md`](file:///d:/website%20project/kaggri%20ox/simulations/results/phase_b1_r3_retry/verification_report.md)

### 2. Complete Purchase Lifecycle Verification
Authoritative observations before and after each action confirm the full lifecycle sequence:

```text
Step 222 (Day 9, Hour 6):
  Pre-Action Cash: $2,266.00 | Reserve: $300.00 | Discretionary Cash: $1,966.00
  WholeFarmPlanner recommends PURCHASE | SWTrancheController approves (sw_purchase_approved = True)
  OrderBuilder checks: $1,966.00 < $2,000.00 land price -> BUY_LAND dropped (reason: "budget")
  Final Action Emitted: [] (BUY_LAND omitted) | Unlocked: ['NW', 'NE'] (SW remains LOCKED)
↓
Steps 223–225:
  Controller preserves approval state without permanent lockup (sw_land_order_emitted = False)
  Retries evaluated turn-by-turn while cash remains below $2,300 threshold
↓
Step 226 (Day 9, Hour 10):
  Pre-Action Cash: $3,261.00 | Discretionary Cash: $2,961.00 >= $2,000.00
  OrderBuilder approves land buy | BUY_LAND emitted in final market action (Retry #4)
  Engine executes BUY_LAND: deducts $2,000, updates farm.unlocked_quadrants to ['NW', 'NE', 'SW']
  Post-Action Cash: $761.00 | Engine purchase confirmed in subsequent observation
↓
Step 233 (Day 9, Hour 17):
  SW Tranche operational: workers plant first admitted SW tile after ownership confirmation
↓
Step 719:
  Full 720 turns complete without assertion errors or fatal exceptions. Final cash: $100,233.00.
```

### 3. Verification Verdict Table

| Step | Day:Hour | Cash Before | Reserve | Discretionary Cash | Approval | Requested | Emitted | Unlocked Before | Unlocked After | Cash After | Drop Reason | Confirmed | Retry # |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 222 | D9:H6 | $2,266.0 | $300.0 | $1,966.0 | True | False | False | False | False | $2,266.0 | budget | False | 0 |
| 223 | D9:H7 | $2,266.0 | $300.0 | $1,966.0 | True | False | False | False | False | $2,266.0 | budget | False | 1 |
| 224 | D9:H8 | $2,266.0 | $300.0 | $1,966.0 | True | False | False | False | False | $2,266.0 | budget | False | 2 |
| 225 | D9:H9 | $2,266.0 | $300.0 | $1,966.0 | True | False | False | False | False | $3,261.0 | budget | False | 3 |
| 226 | D9:H10 | $3,261.0 | $300.0 | $2,961.0 | True | True | True | False | True | $761.0 | None | True | 4 |

**Core Invariants Confirmed**:
- Approval does not equal execution.
- Failed orders do not permanently lock state.
- Zero SW planting occurs before engine unlock confirmation.
- Original B1 results (200 pairs, mean -$9,360.83) remain strictly preserved and isolated.

---

## Part B: Core-Only Production Baseline Performance Ledger

### 1. Panel Configuration
- **Production Mode**: `SW_FORWARD_ARCHITECTURE_MODE = "OFF"` (Core NW + NE only).
- **Discovery Seeds**: 96501, 96502 (previously consumed non-protected discovery seeds).
- **Benchmark Opponents (5)**: `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`.
- **Seats (2)**: 0 and 1.
- **Total Evaluated Matches**: 20 full 720-step episodes (14,400 turns total).
- **Panel Performance Summary**:
  - **Mean Final Cash**: **$99,444.45**
  - **Std Dev**: $7,871.49
  - **Min / Max**: $87,357.00 / $111,271.00
  - **Target**: $130,000.00
  - **Target Gap**: **$30,555.55**

---

### 2. Category A: Crop Production Ledger (NW vs. NE)

| Metric | NW Quadrant | NE Quadrant | Total Farm | Interpretation |
| :--- | :--- | :--- | :--- | :--- |
| **Available Productive Tiles** | 25 tiles | 25 tiles (once unlocked) | 50 tiles | All 20 matches unlocked NE at Step 145 ($1,000) |
| **Mean Idle Tile-Turns / Match** | 2,215.3 | 1,818.9 | **4,034.2** | ~5.6 productive tiles sit empty every hour |
| **Mean Missed Watering Turns** | 2,420.1 | 2,334.1 | **4,754.2** | Planted crops left unwatered, delaying maturity |
| **Mean Harvest Delay Tile-Turns**| 4,512.0 | 4,456.1 | **8,968.1** | Mature harvest-ready crops left unharvested |
| **Total Weeds Spawned** | 4,810 | 4,794 | 9,604 | Result of unwatered plants decaying |
| **Mean Unharvested Crops at Step 720**| 1.9 tiles | 1.9 tiles | 3.8 tiles | Final-cycle plantings that did not mature in time |

**Primary Crop Finding**: Production is primarily lost through **harvest delay** and **replanting latency**, not lack of land. Crops sit harvest-ready for an average of ~9,000 tile-turns across the season because workers are busy traveling across quadrants.

---

### 3. Category B: Worker Execution Ledger

Across all 20 matches, workers took **147,557 individual action turns**:

| Action Category | Action Types | Count | Percentage | Operational Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **Movement** | `NORTH`, `SOUTH`, `EAST`, `WEST` | **95,640** | **64.82%** | Workers traveling between tiles, shed, and quadrants |
| **Productive Farm Operations** | `WATER`, `HARVEST`, `FEED`, `CARE`, `PLANT`, `COLLECT_FERTILIZER`, `BUILD_*`, `DROP`, `PICKUP`, `PLACE` | **43,415** | **29.42%** | Actual value-generating farm tasks |
| **Idle / Pass** | `PASS` | **8,502** | **5.76%** | Worker standing idle awaiting task assignment |

**Key Worker Execution Insights**:
- **Quadrant Hopping**: Workers cross between NW and NE **689.2 times per match** (~29 times per day).
- **Shed Congestion**: Workers visit shed access tiles **858.5 times per match** (~36 times per day).
- **Efficiency Paradox**: Nearly two-thirds of the labor force's entire operational existence is spent walking rather than working.

---

### 4. Category C: Livestock & Feed Ledger

| Metric | Measured Baseline Value | Assessment |
| :--- | :--- | :--- |
| **Mean Animals Purchased** | **8.65 animals / match** | Mostly Cows (7.0) and Sheep (1.65); Geese = 0 |
| **Pastures Built** | 13.0 pastures / match | Dedicated pasture cluster in NW/NE |
| **Daily Feeding Tasks Due** | 258.0 animal-days / match | Scheduled animal maintenance |
| **Daily Feeding Completed** | 248.9 feedings / match | High feeding prioritization |
| **Feeding Compliance Rate** | **96.48%** | Excellent survival protection |
| **Total Animal Escapes** | **0 escapes** (across all 20 matches) | Zero losses due to starvation |
| **Feed Wheat Purchased** | 902.0 units / match ($22,550.00) | Purchased on market to supplement core wheat |

**Livestock Insight**: Animal management is safe and highly compliant (0 escapes). However, animal scaling stalls at ~8–9 animals because the agent relies on expensive purchased wheat rather than growing sufficient feed on-farm.

---

### 5. Category D: Capital & Cash Allocation Ledger

| Expenditure Category | Mean Spending / Match | Percentage of Budget |
| :--- | :--- | :--- |
| **Farmhand Hiring** | $29,400.00 | 44.3% |
| **Feed Wheat Purchases** | $22,550.00 | 34.0% |
| **Seed Purchases** | $9,610.25 | 14.5% |
| **Animal Purchases** | $3,855.00 | 5.8% |
| **Land Purchase (NE)** | $1,000.00 | 1.5% |
| **Total Outflows** | **$66,415.25** | 100.0% |

**Capital Hoarding Finding**:
- The agent held $\ge \$2,000.00$ in liquid cash for an average of **439.6 turns per match** (over 60% of the entire game).
- While $300 is necessary as a feed/survival reserve, holding $2,000–$5,000 in liquid capital during Days 10–20 delays livestock reinvestment by 3–6 days.

---

### 6. Category E: Storage & Market Execution Ledger

| Metric | Measured Value | Operational Impact |
| :--- | :--- | :--- |
| **Peak Shed Occupancy** | **100 units** (hit in 100% of matches) | Storage limit reached during peak harvests |
| **Shed Full Turns (>= 95 units)** | **9.9 turns / match** | Temporary pauses in harvesting |
| **Market Orders Requested** | 529.9 orders / match | Order generation across days |
| **Market Orders Emitted** | 736.1 orders / match | Multi-unit lockstep orders |
| **Market Orders Dropped** | **71.0 orders / match** | Orders trimmed due to budget or 10-slot cap |
| **Endgame Unsold Inventory Value**| **$0.00** | EndgameLiquidator successfully clears inventory |

---

## Part C: Ranked Core-Farm Bottlenecks

### 1. Bottleneck Ranking by Measured Evidence and Impact

| Rank | Bottleneck | Category | Evidence Level | Matches Affected | Turns Affected / Match | Directly Measured Loss | Estimated Opportunity Cost | Subsystem |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | **WORKER_TRAVEL_OVERHEAD** | Worker Dispatch | **Observed** | 20 / 20 | 4,782.0 worker-turns | — | **~$11,955.00** | `AdaptiveZonalDispatch` / `WorkerManager` |
| **2** | **CORE_TILE_IDLE** | Land Utilization | **Observed** | 20 / 20 | 4,034.2 tile-turns | — | **~$5,042.81** | `CentralPlanner` / `CropAccounting` |
| **3** | **HARVEST_DELAY** | Crop Operations | **Observed** | 20 / 20 | 8,968.1 tile-turns | — | **~$4,500.00** | `MaturityHarvesting` / `TaskScheduler` |
| **4** | **CAPITAL_ALLOCATION_DELAY** | Capital Efficiency | **Estimated** | 20 / 20 | 439.6 turns | — | **~$2,197.75** | `PreNECapitalPolicy` / `LivestockReinvestment` |
| **5** | **MARKET_ORDER_DROPPED** | Market Order Cap | **Observed** | 20 / 20 | 71.0 orders | — | **~$1,064.25** | `OrderBuilder` / `ResourceLedger` |
| **6** | **ENDGAME_UNSOLD_INVENTORY** | Market Liquidation | **Observed** | 0 / 20 | 0.0 turns | **$0.00** | $0.00 | `EndgameLiquidator` (Working properly) |

---

### 2. Separation of Evidence Levels

1. **Observed (Direct Engine Facts)**:
   - Worker movement consumes 64.82% of all turns.
   - Core productive tiles sit empty for 4,034.2 tile-turns per match.
   - Mature crops wait 8,968.1 tile-turns before being harvested.
   - Zero animals starve or escape.
   - Zero unsold goods remain in the shed at Day 29.
2. **Estimated (Model-Supported Economics)**:
   - Converting 25% of redundant travel steps into watering/harvesting actions would yield ~$11,955.00 in additional farm output.
   - Continuous core tile replanting (eliminating the ~5.6 idle tiles/hour) would generate ~$5,042.81 in staple crop revenue.
   - Earlier animal purchasing (reinvesting cash > $1,500 on Days 10–14) would generate ~$2,197.75 in additional milk/wool cycles.
3. **Hypothesized (Plausible Targets for Follow-Up Experiments)**:
   - Strict worker zonal pinning (allocating dedicated workers to NW vs NE) will cut quadrant crossings by >60% without starving feed tasks.

---

## Part D: Top 3 Candidates for Next Optimization Experiment

### Candidate 1 (Recommended): Strict Zonal Worker Locality (Anti-Quadrant Hopping)
- **Subsystem**: `agent/execution/adaptive_zonal_dispatch.py` and `worker_manager.py`.
- **Observed Failure Mechanism**: Workers constantly switch quadrants (689.2 times/match), walking across the center shed to perform isolated tasks, causing movement actions to consume 64.82% of worker capacity.
- **Minimal Intervention**: Implement strict home-quadrant affinity for farmhands. Hands assigned to NW service NW crops and livestock; hands assigned to NE service NE crops. Only designated transport hands or the main farmer may cross quadrants.
- **Safety / Economic Tradeoff**: Potential delay if a high-priority task in NE has no local worker, though localized workers can easily handle local tasks.
- **Primary Measurable Outcome**: Reduction of movement action percentage from 64.8% to <45%; increase in productive actions from 29.4% to >45%; paired delta > +$8,000.
- **Required Regression Tests**: Test worker task assignment locality, ensure zero animal feeding starvation, verify well-adjacent watering.
- **Expected Experiment Size**: 40 paired matches (4 seeds $\times$ 5 opponents $\times$ 2 seats).

### Candidate 2: Continuous Immediate Core Tile Replanting
- **Subsystem**: `agent/strategy/central_planner.py` and `macro_planner.py`.
- **Observed Failure Mechanism**: Core productive tiles sit empty for 4,034.2 tile-turns/match because seed ordering and planting intents lag 1–3 days behind harvests.
- **Minimal Intervention**: Pre-queue replacement seeds 1 day prior to crop maturity so seeds are already in `private["seeds"]` at harvest time, enabling same-turn or next-turn replanting.
- **Primary Measurable Outcome**: Reduction of idle tile-turns by >50%; paired delta > +$4,000.

### Candidate 3: Dynamic Capital Reinvestment Thresholds
- **Subsystem**: `agent/strategy/pre_ne_capital_policy.py` and `livestock_reinvestment.py`.
- **Observed Failure Mechanism**: The agent sits on $\ge \$2,000$ cash for 439 turns, delaying animal purchases until late in the season when remaining lifespan yields fewer milk/wool cycles.
- **Minimal Intervention**: Reduce post-NE cash retention threshold from $2,000 to $600 (maintaining a 2-day feed reserve) once NE is unlocked, immediately compounding surplus into cows/sheep.
- **Primary Measurable Outcome**: Increase mean animals purchased from 8.65 to 14.0; paired delta > +$5,000.

---

## Part E: Implementation Prompt for Next Experiment

Below is the implementation prompt for the single most promising next experiment:

```markdown
# Kaggriculture — Phase C0: Strict Zonal Worker Locality & Travel Reduction Experiment

## Objective
Implement strict zonal worker locality in `agent/execution/adaptive_zonal_dispatch.py` to reduce movement overhead from 64.8% of worker turns to <45%, converting walking time into immediate watering, harvesting, and replanting on the core NW+NE farm.

## Target Baseline
- Branch: `experiment/sw-forward-architecture-phase-a`
- Production Baseline: `SW_FORWARD_ARCHITECTURE_MODE = "OFF"`
- Discovery Panel: 40 paired matches (Seeds 96501–96504, 5 benchmark opponents, Seats 0 and 1)

## Intervention Details
1. In `adaptive_zonal_dispatch.py`, assign each hired farmhand a permanent home quadrant (`NW` or `NE`).
2. Enforce a strong penalty in the Hungarian task-assignment cost matrix for tasks located outside the worker's home quadrant.
3. Reserve quadrant-crossing exclusively for the main farmer (handling market drops and emergency feed delivery).
4. Maintain feed-safety invariants: an out-of-zone worker may only be dispatched if a local animal's feeding deadline is <= 3 turns from expiry.

## Evaluation Metric
- Primary: Mean Paired Delta = Treatment_Cash - Baseline_Cash (target: >= +$8,000/match).
- Secondary: Worker movement turn percentage <= 45%; quadrant crossing count <= 250/match.
- Safety: Zero animal starvation escapes; 100% test pass rate across `agent/tests`.
```

---

## Part F: Test Suite & Governance Summary

1. **Targeted Tests**:
   - `pytest agent/tests/test_sw_branch_treatment.py -v`
   - **19 passed** in 1.90s (including new regression test `test_sw_purchase_retry_lifecycle_verification`).
2. **Full Repository Test Suite**:
   - `pytest agent/tests`
   - **1,163 passed** in 231.15s (0 failed, 0 errors, 100% pass rate).
3. **Submission Package**:
   - `scripts/build_submission.py` synchronized 44 modules to `submission/` and built `dist/submission.zip` (325,206 bytes).
   - Clean isolated execution verified: 720 turns, P0=$104,897.00.
4. **Governance & Constraints**:
   - `SW_FORWARD_ARCHITECTURE_MODE = "OFF"` verified as production default.
   - Protected seeds `98001–98050` remain strictly untouched.
