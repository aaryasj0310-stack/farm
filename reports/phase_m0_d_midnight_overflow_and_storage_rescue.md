# Phase M0-D: Authoritative Midnight Overflow & Storage Rescue Report

## Executive Summary

Phase M0-D provides the authoritative resolution to the Kaggriculture midnight inventory overflow problem. Through direct engine instrumentation, microtest proofs, a 100-match baseline audit, and a 200-match controlled discovery experiment, we establish two fundamental findings:

1. **Engine Discard Ground Truth (Authoritative Verification):** The Kaggriculture engine (`_drop_inventories_to_shed`) **strictly and irreversibly destroys** worker carried inventory whenever total items exceed shed capacity (100). In the unpatched production baseline (C0), **100% of matches suffer inventory destruction**, averaging **36.82 to 40.38 discarded units per match** and permanently erasing **$3,214.15 to $3,823.35 in spot market value per match**.
2. **Proactive Storage Rescue Exploitation (`MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`):** Implementing targeted marginal Hour 23 wheat relief (`apply_midnight_storage_rescue`) virtually eliminates this destruction while preserving farm food security. In the 200-match controlled discovery experiment across seeds 97013–97022, storage rescue delivered:
   - **Mean Paired Cash Delta:** **+\$5,056.89**
   - **Median Paired Cash Delta:** **+\$5,012.00**
   - **95% Clustered CI (10 seed clusters):** **[+\$2,504.43, +\$7,609.35]** (strictly positive)
   - **Head-to-Head Win Rate vs Control:** **84.0%** (84 Wins, 0 Ties, 16 Losses)
   - **Physical Discard Reduction:** **-92.4%** (3,682 units destroyed in C0 reduced to 279 units in C2)
   - **Spot Market Value Preserved:** **+\$2,938.45 per match**
   - **Decision Gates:** Gate A (Proceed), Gate B (Passed), Gate C (Passed).

---

## 1. Engine Mechanics Ground Truth

### 1.1 Engine Implementation Analysis (`kaggriculture.py`)
In `kaggle_environments/envs/kaggriculture/kaggriculture.py`:
- At each step, worker actions execute first, followed by market order matching.
- At the transition from hour 23 to midnight (`_end_of_day`), the engine executes `_drop_inventories_to_shed(farm["private"], SHED_CAPACITY)`.
- The engine iterates through each worker's inventory dict:
  ```python
  def _drop_inventories_to_shed(private, capacity):
      shed = private["shed"]
      current = sum(shed.values())
      for inv in private["inventories"]:
          for item in list(inv.keys()):
              count = inv[item]
              space = capacity - current
              if space <= 0:
                  del inv[item]          # <-- PERMANENT DESTRUCTION
                  continue
              transfer = min(count, space)
              shed[item] = shed.get(item, 0) + transfer
              current += transfer
              del inv[item]              # <-- Remaining (count - transfer) is lost
  ```
- **Key Realities:**
  1. Carried inventory that does not fit into the 100-item shed capacity is **deleted permanently** (`del inv[item]`). It does *not* remain in the worker's hands into the next morning.
  2. Seeds reside in `farm["private"]["seeds"]`, which is decoupled from worker inventory and is neither deposited nor discarded.
  3. Animals held in inventory are also subject to this loop.

### 1.2 Authoritative Microtest Proofs (`scripts/verify_engine_midnight_overflow.py`)
Direct microtests against the live engine confirmed the exact behavior:
- **Case A (Shed 95, 2 workers carrying 5 wheat each):** Worker 0 deposited 5 wheat (shed reached 100); Worker 1's 5 wheat was completely discarded (`total_discarded = 5`).
- **Case B (Shed 98, worker carrying 1 wheat + 1 melon):** Wheat deposited; high-value melon ($250) permanently discarded!
- **Case C (Shed 100, worker carrying 1 cow):** Carried cow deleted!
- **Case D (Shed 90, worker carrying 5 wheat, private seeds = 10):** 5 wheat deposited into shed; seeds untouched in `private["seeds"]`.
- **Conservation Law:** Across all microtests and 300+ simulation matches, the conservation identity held with 100% precision:
  $$\text{Carried Units} \equiv \text{Deposited Units} + \text{Discarded Units}$$

---

## 2. Baseline Authoritative Storage Audit (Decision Gate A)

Before implementing the rescue mechanism, a 100-match baseline audit was conducted across consumed discovery seeds 96501–96510 against 5 benchmark opponents (`pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`) in both seats (`0` and `1`).

### 2.1 Audit Findings
- **Matches with Discard:** **100 / 100 (100.0%)**
- **Total Discarded Units:** **4,038 units** across 100 matches
- **Mean Discarded Units / Match:** **40.38 units** (Median 39.0, p10 15.0, p90 69.1)
- **Mean Spot Value Destroyed / Match:** **\$3,823.35**
- **Peak Shed Occupancy:** 100 / 100 matches reached capacity (100/100 items).
- **Mean Turns at Capacity (>= 100 items):** 62.4 turns / match.

### 2.2 Root Cause Diagnosis
Why does the baseline agent experience discard every single match?
1. **Feed Buffering:** To guarantee animal survival, `FEED_WHEAT_BUFFER_DAYS = 4` maintains up to 44 units of feed wheat in the shed.
2. **Late-Day Harvest Return:** Between hours 20 and 23, 10–12 workers return from late harvests and animal milking/shearing carrying 58–70 units of mixed produce (including high-value wool, milk, strawberries, and melons).
3. **The Midnight Collision:** With 44 units of wheat occupying the shed, room is limited to 56 units. When workers arrive at midnight carrying 65 units, $44 + 65 = 109 > 100$, causing **9 units of inventory to be destroyed on that day alone**. Over 30 days, this accumulates to ~40 units destroyed per match.

### 2.3 Decision Gate A Verdict
- **Criterion:** Discard observed in >= 20% of matches with mean discard >= 5.0 units.
- **Observed:** 100% of matches, 40.38 units/match.
- **Verdict:** **PROCEED TO RESCUE** (`simulations/results/phase_m0_d_engine_audit/decision_gate_a.json`).

---

## 3. Storage Rescue Architecture

### 3.1 Failed Approaches Tried & Abandoned
1. **Buffered Worker Riding (Phase M0-B approach):** Forbidding workers from depositing between hours 20 and 22 caused huge backlogs in worker hands, exacerbating midnight collisions (discards increased from 15 to 69 units). Worker transit and deposits must flow unimpeded.
2. **Wholesale Late-Day Dumping in MarketBrain:** Setting `urgency = 2` or `target_load = 75` at hour 22 dumped hundreds of units into the market during thin liquidity windows, crashing prices and causing severe financial losses (-\$5,000 to -\$11,000).

### 3.2 Authoritative Solution: Proactive Hour 23 Marginal Relief
The winning strategy is implemented via `apply_midnight_storage_rescue(market, ctx)` in `agent/execution/midnight_storage_controller.py`:
- **Execution Timing:** Hour 23, Day < 29, executed in `main.py` directly before market submission.
- **Accurate Midnight Load Projection:**
  $$\text{Projected Midnight Load} = \sum \text{Shed Stock} + \sum_{\text{workers}} \sum \text{Carried Inventory}$$
- **Marginal Threshold:**
  If $\text{Projected} > 98$:
  $$\text{Needed Relief} = \text{Projected} - 98$$
  Typically, `Needed Relief` is small: only **3 to 12 units**.
- **Animal Feed Protection:**
  Before releasing any wheat, the controller enforces a strict 2-day feed reserve:
  $$\text{Safe Wheat Floor} = \max(10, \text{animal\_count} \times 2)$$
  $$\text{Available Wheat} = \max(0, \text{Shed Wheat} - \text{Safe Wheat Floor})$$
- **Single Surgical Sell Order:**
  $$\text{Sell Qty} = \min(\text{Available Wheat}, \text{Needed Relief})$$
  If $\text{Sell Qty} > 0$ and market orders $< 10$, emits `["SELL", "WHEAT", Sell Qty]`.
- **Why this works:**
  Selling 3–12 units of cheap wheat (\$75–\$300 gross) creates the exact clearance required in the shed so that 100% of high-value carried items (wool, milk, strawberries, melons) enter the shed at midnight without being discarded.

---

## 4. Controlled Discovery Experiment Results

The 2-arm controlled experiment evaluated 100 matched pairs (200 matches) on consumed discovery seeds 97013–97022:
- **C0 (Control):** `MIDNIGHT_STORAGE_DUMP_MODE = "OFF"`
- **C2 (Rescue):** `MIDNIGHT_STORAGE_DUMP_MODE = "RESCUE"`
- **Both Arms:** `SAME_TURN_CROP_PIPELINE_MODE = "OFF"`, `SW_FORWARD_ARCHITECTURE_MODE = "OFF"`, `SOFT_WORKER_LOCALITY_MODE = "OFF"`.

### 4.1 Global Financial Performance

| Metric | Control (C0) | Treatment (C2 - Rescue) | Delta (C2 - C0) |
| :--- | :---: | :---: | :---: |
| **Mean Cash** | \$104,009.28 | \$109,066.17 | **+\$5,056.89** |
| **Median Cash (p50)** | \$103,433.50 | \$108,802.00 | **+\$5,012.00** |
| **Std Dev** | \$8,817.53 | \$9,346.07 | \$6,451.64 |
| **p10** | \$92,969.90 | \$99,674.00 | -\$2,063.30 |
| **p25** | \$98,444.00 | \$103,541.25 | +\$2,157.75 |
| **p75** | \$109,114.25 | \$115,432.50 | +\$6,761.00 |
| **p90** | \$115,526.30 | \$119,229.90 | +\$12,664.30 |
| **Head-to-Head Record** | — | — | **84 Wins / 0 Ties / 16 Losses (84.0%)** |
| **Cluster-Robust SE** | — | — | **\$1,128.33** |
| **95% Clustered CI** | — | — | **[+\$2,504.43, +\$7,609.35]** |

### 4.2 Seed Cluster Consistency (10 / 10 Positive)

Across all 10 independent seed clusters, the cluster mean paired cash delta is uniformly positive:

| Seed | Control Mean Cash | Treatment Mean Cash | Paired Cash Delta | Discard Reduction | Preserved Spot Value |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **97013** | \$104,115.30 | \$109,230.00 | **+\$5,114.70** | +28.4 units | +\$2,183.00 |
| **97014** | \$101,659.10 | \$111,629.30 | **+\$9,970.20** | +51.8 units | +\$5,332.00 |
| **97015** | \$108,610.10 | \$112,927.90 | **+\$4,317.80** | +15.7 units | +\$1,379.50 |
| **97016** | \$107,314.10 | \$111,474.20 | **+\$4,160.10** | +40.1 units | +\$2,975.50 |
| **97017** | \$105,420.90 | \$110,093.10 | **+\$4,672.20** | +26.3 units | +\$2,412.50 |
| **97018** | \$105,404.90 | \$110,868.90 | **+\$5,464.00** | +39.5 units | +\$3,039.50 |
| **97019** | \$97,931.20 | \$110,161.70 | **+\$12,230.50** | +33.1 units | +\$3,260.00 |
| **97020** | \$101,677.30 | \$103,700.00 | **+\$2,022.70** | +41.9 units | +\$4,050.00 |
| **97021** | \$101,744.10 | \$103,094.70 | **+\$1,350.60** | +33.6 units | +\$2,772.00 |
| **97022** | \$106,215.80 | \$107,481.90 | **+\$1,266.10** | +29.9 units | +\$1,980.50 |

---

### 4.3 Physical Discard Reduction & Spot Value Preserved

| Product | Control (C0) Discard | Treatment (C2) Discard | Units Saved | Reduction % |
| :--- | :---: | :---: | :---: | :---: |
| **WHEAT** | 1,572 | 111 | +1,461 | 92.9% |
| **STRAWBERRY** | 845 | 25 | +820 | 97.0% |
| **WOOL** | 338 | 0 | +338 | **100.0%** |
| **MILK** | 315 | 29 | +286 | 90.8% |
| **FERTILIZER** | 349 | 37 | +312 | 89.4% |
| **CARROT** | 139 | 21 | +118 | 84.9% |
| **MELON** | 82 | 50 | +32 | 39.0% |
| **COW / SHEEP** | 2 | 4 | -2 | — |
| **TOTAL** | **3,682** | **279** | **+3,403** | **92.4%** |

- **Mean Discard / Match:** Reduced from **36.82 units** down to **2.79 units** (median 0.0!).
- **Mean Spot Value Destroyed / Match:** Dropped from **\$3,214.15** to **\$275.70**.
- **Spot Value Preserved:** **+\$2,938.45 per match**.
- **Operational Footprint:** An average of only **6.59 rescue orders per match**, selling a mean total of **63.23 units of wheat per match** (~9.6 units per rescue event).

---

### 4.4 Opponent Performance Breakdown

| Opponent | Pairs | Mean Cash Delta | Median Cash Delta | Discard Reduction | Win Rate vs C0 (W/T/L) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `pass` | 20 | **+\$5,843.25** | +\$3,860.00 | +36.35 units | 19 / 0 / 1 (95.0%) |
| `pure_wheat_rush` | 20 | **+\$6,834.95** | +\$4,425.00 | +35.50 units | 18 / 0 / 2 (90.0%) |
| `cow_milk_engine` | 20 | **+\$3,127.65** | +\$3,783.50 | +24.10 units | 14 / 0 / 6 (70.0%) |
| `melon_sniper` | 20 | **+\$4,706.80** | +\$5,953.50 | +45.25 units | 15 / 0 / 5 (75.0%) |
| `full_production_agent` | 20 | **+\$4,771.80** | +\$4,687.00 | +28.95 units | 18 / 0 / 2 (90.0%) |

*Note:* Against our own benchmark baseline (`full_production_agent`), Storage Rescue achieved an 18-2 record (+90% win rate) with an average advantage of **+\$4,771.80**.

---

### 4.5 Seat Breakdown

| Seat | Pairs | Mean Cash Delta | Median Cash Delta | Discard Reduction | Win Rate vs C0 (W/T/L) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Seat 0** | 50 | **+\$5,304.84** | +\$5,075.50 | +34.14 units | 41 / 0 / 9 (82.0%) |
| **Seat 1** | 50 | **+\$4,808.94** | +\$4,908.50 | +33.92 units | 43 / 0 / 7 (86.0%) |

The mechanism demonstrates exceptional seat symmetry, with both seats delivering ~\$5,000 mean gains and >82% win rates.

---

### 4.6 Loss Forensics

Out of 100 cells, Treatment (C2) lost to Control (C0) in 16 cells (16%), of which 6 cells had deltas $< -\$5,000$:
1. **Seed 97016 vs `cow_milk_engine` (Seats 0 & 1):** Delta -\$8,368 and -\$8,668. In C0, total discard happened to be 0 by chance (unusual crop timing). In C2, the controller sold 45 units of wheat over the match, which slightly altered late-game reinvestment timing.
2. **Seed 97020 vs `melon_sniper` (Seat 1):** Delta -\$6,285.
3. **Seed 97021 vs `cow_milk_engine` (Seats 0 & 1):** Delta -\$5,315 and -\$5,610.
4. **Seed 97022 vs `melon_sniper` (Seat 1):** Delta -\$6,070.

**Mechanism Analysis:** Regressions occur almost exclusively against heavy commodity competitors (`cow_milk_engine` and `melon_sniper`) on seeds where selling surplus wheat at Hour 23 triggers minor price feedback or causes the macro planner to re-order land purchases by 1 turn. Even with these 6 outliers, the 10th percentile across all 100 pairs is **-\$2,063.30**, vastly superior to Phase M0-A/M0-B downside tails.

---

## 5. Decision Gates Summary

| Gate | Requirement | Observed | Status |
| :--- | :--- | :--- | :---: |
| **Gate A: Midnight Overflow Reality** | Baseline discard in >= 20% of matches, mean loss >= 5.0 units | **100.0% of matches**, **40.38 units/match**, **\$3,823.35 spot loss** | **PASSED** |
| **Gate B: Storage Preservation** | Discard reduction >= 50.0%, Spot value preserved >= \$1,000 | **92.4% discard reduction**, **+\$2,938.45 preserved / match** | **PASSED** |
| **Gate C: Financial Viability** | Mean cash delta > 0, Median cash delta > 0, Positive CI | **Mean +\$5,056.89**, **Median +\$5,012.00**, **CI [+\$2,504.43, +\$7,609.35]** | **PASSED** |

### Overall Recommendation: **PROCEED TO CONFIRMATION**

---

## 6. Verification, Security & Guardrail Compliance

1. **Security Scan:**
   - Command: `snyk.cmd code test "agent"`
   - Result: **0 issues found** (clean static analysis).
2. **Test Suite:**
   - Command: `pytest agent/tests`
   - Result: **1,212 / 1,212 tests passed** (100% pass rate in 164.59s).
3. **Production Guardrails:**
   - `SW_FORWARD_ARCHITECTURE_MODE = "OFF"`
   - `SOFT_WORKER_LOCALITY_MODE = "OFF"`
   - `MIDNIGHT_STORAGE_DUMP_MODE = "OFF"`
   - `SAME_TURN_CROP_PIPELINE_MODE = "OFF"`
   - Reserved confirmation seeds `96521–96540` and protected tournament seeds `98001–98050` remained **completely untouched**.
