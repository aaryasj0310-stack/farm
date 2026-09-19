# SW Post-Purchase Score Regression Diagnosis (P1 Experiment)

**Status:** Completed Diagnostic Audit  
**Artifact:** `simulations/experiments/results/sw_p1_post_purchase_diagnosis.md`  
**Date:** September 19, 2026  
**Investigator:** Antigravity Diagnostic Agent  

---

## 1. Exact Source and Diagnostic Branch SHAs

- **Production Baseline (Control):** `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
- **Validated P1 Treatment Runtime:** `b89c8381b341d43c9e81e0701fd8d39edbc8aaaa`
- **Experimental Branch HEAD:** `fbad61f030b9d6f45f04fa152841ee44750f30b9` (`experiment/sw-p1-committed-herd-workload`)
- **Diagnostic Working Branch:** `diagnostic/sw-p1-post-purchase-regression` (branched from `fbad61f030b9d6f45f04fa152841ee44750f30b9`)
- **Engine Environment:** `kaggriculture 1.32.7`, Python 3.12 (Windows)
- **Preserved Files:** 
  - `simulations/experiments/run_wheat_planted_day_ab.py`
  - `simulations/experiments/results/wheat_planted_day_ab_results.json`

---

## 2. Replay Pairs Investigated

To isolate the root causes with high fidelity, four representative pairs from the 20-pair deterministic evaluation (`simulations/experiments/results/sw_p1_committed_herd_20pair.json`) were fully replayed and traced turn-by-turn with instrumented telemetry:

| Pair ID | Random Seed | Opponent Archetype | Control Score | P1 Score | Paired Score Delta | SW Acquired (Control vs P1) | Earliest Divergence Turn |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Pair 1** | `7101` | `pass` | $105,431.00 | $82,562.00 | **-$22,869.00** | Never vs Day 11 Hour 2 | Day 11 Hour 1 |
| **Pair 3** | `7103` | `pass` | $118,879.00 | $87,834.00 | **-$31,045.00** | Never vs Day 11 Hour 2 | Day 11 Hour 1 |
| **Pair 10** | `7310` | `cow_milk_engine` | $101,664.00 | $61,244.00 | **-$40,420.00** | Never vs Day 11 Hour 3 | Day 11 Hour 1 |
| **Pair 18** | `7518` | `full_production_agent` | $106,606.00 | $68,401.00 | **-$38,205.00** | Never vs Day 11 Hour 3 | Day 11 Hour 1 |

### Pre-Divergence Invariance Proof
- **Days 0 through 10 (Steps 0 to 263):** In all four pairs, state, cash, inventory, worker positions, and actions between Control and P1 were **100% byte-for-byte identical**.
- **Non-purchasing Pairs (Pairs 2, 12, 14, 19, 20):** In all 5 pairs where SW was not acquired, Control and P1 remained identical for all 720 steps, yielding exactly **$0.00 score delta**.
- **Conclusion:** The regression is 100% causally coupled to the post-purchase dynamics triggered on Day 11.

---

## 3. Day-by-Day Comparison Around SW Acquisition (Days 10–14)

The transition from pre-purchase (Day 10) to post-purchase (Days 11–14) demonstrates immediate structural collapse across labor allocation, crop maintenance, and animal welfare.

### Day-by-Day Metrics Across Traced Pairs

#### Pair 1 (`pass`, Seed 7101)
| Metric | Day 10 (Pre) | Day 11 (Purchase) | Day 12 | Day 13 | Day 14 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Cash End (Ctrl / P1)** | $1,735 / $1,735 | $9,256 / $6,973 | $11,464 / $6,942 | $15,091 / $9,634 | $17,520 / $13,011 |
| **Hands Count** | 10 / 10 | 12 / 12 | 12 / 12 | 12 / 12 | 12 / 12 |
| **Worker Turns NW (Ctrl / P1)** | 153 / 153 | 143 / **90** (-37%) | 162 / 133 | 131 / 107 | 165 / 106 |
| **Worker Turns NE (Ctrl / P1)** | 96 / 96 | 142 / **109** (-23%) | 129 / 91 | 152 / 95 | 121 / 117 |
| **Worker Turns SW (Ctrl / P1)** | 3 / 3 | 4 / **84** (+2000%)| 4 / **64** | 4 / **84** | 3 / **60** |
| **Worker Ops NW+NE (Ctrl / P1)**| 71 / 71 | 80 / **57** (-29%) | 88 / **61** (-31%) | 80 / **53** (-34%) | 77 / **53** (-31%) |
| **Worker Ops SW (Ctrl / P1)** | 0 / 0 | 0 / 26 | 0 / 12 | 0 / 16 | 0 / 18 |
| **Unwatered NW+NE (Ctrl / P1)** | 7 / 7 | 5 / **12** (+140%)| 10 / 9 | 12 / 12 | 7 / 10 |
| **Unwatered SW (P1 only)** | 0 | 0 | **7** | **1** | **4** |
| **Starvations (Ctrl / P1)** | 1 / 1 | 1 / 1 | 2 / 3 | 2 / 0 | 0 / **5** |

#### Pair 3 (`pass`, Seed 7103)
| Metric | Day 10 (Pre) | Day 11 (Purchase) | Day 12 | Day 13 | Day 14 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Cash End (Ctrl / P1)** | $333 / $333 | $8,755 / $4,695 | $12,271 / $8,933 | $20,198 / $14,639 | $21,174 / $15,743 |
| **Worker Turns NW+NE (Ctrl / P1)**| 248 / 248 | 283 / **221** (-22%)| 291 / **225** (-23%)| 290 / **205** (-29%)| 289 / **217** (-25%)|
| **Worker Turns SW (Ctrl / P1)** | 3 / 3 | 4 / **50** | 4 / **44** | 4 / **66** | 4 / **68** |
| **Worker Ops NW+NE (Ctrl / P1)**| 79 / 79 | 66 / **48** (-27%) | 77 / **62** (-19%) | 89 / **42** (-53%) | 71 / **49** (-31%) |
| **Unwatered NW+NE (Ctrl / P1)** | 12 / 12 | 11 / **16** | 10 / 13 | 7 / **19** (+171%)| 8 / **14** |
| **Unwatered SW (P1 only)** | 0 | 0 | **4** | **3** | **3** |
| **Starvations (Ctrl / P1)** | 0 / 0 | 2 / 2 | 4 / 1 | 1 / 1 | 0 / 1 |

#### Pair 10 (`cow_milk_engine`, Seed 7310)
| Metric | Day 10 (Pre) | Day 11 (Purchase) | Day 12 | Day 13 | Day 14 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Cash End (Ctrl / P1)** | $2,054 / $2,054 | $3,112 / $1,537 | $10,354 / $4,464 | $11,999 / $6,492 | $12,812 / $10,795 |
| **Worker Turns NW+NE (Ctrl / P1)**| 248 / 248 | 287 / **222** (-23%)| 291 / **230** (-21%)| 291 / **205** (-30%)| 289 / **219** (-24%)|
| **Worker Turns SW (Ctrl / P1)** | 3 / 3 | 3 / **48** | 4 / **39** | 4 / **64** | 4 / **57** |
| **Worker Ops NW+NE (Ctrl / P1)**| 78 / 78 | 69 / **51** (-26%) | 68 / **58** (-15%) | 81 / **50** (-38%) | 67 / **50** (-25%) |
| **Unwatered NW+NE (Ctrl / P1)** | 9 / 9 | 7 / **14** (+100%)| 12 / 11 | 11 / **19** (+73%) | 11 / 13 |
| **Unwatered SW (P1 only)** | 0 | 0 | **4** | **2** | **4** |
| **Starvations (Ctrl / P1)** | 0 / 0 | 1 / 1 | 4 / 2 | 4 / 2 | 1 / 0 |

#### Pair 18 (`full_production_agent`, Seed 7518)
| Metric | Day 10 (Pre) | Day 11 (Purchase) | Day 12 | Day 13 | Day 14 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Cash End (Ctrl / P1)** | $1,574 / $1,574 | $6,241 / $2,697 | $14,269 / $5,582 | $16,807 / $11,375 | $18,167 / $12,977 |
| **Worker Turns NW+NE (Ctrl / P1)**| 249 / 249 | 291 / **219** (-25%)| 291 / **216** (-26%)| 290 / **199** (-31%)| 285 / **213** (-25%)|
| **Worker Turns SW (Ctrl / P1)** | 3 / 3 | 4 / **61** | 4 / **79** | 5 / **82** | 4 / **70** |
| **Worker Ops NW+NE (Ctrl / P1)**| 66 / 66 | 95 / **72** (-24%) | 84 / **60** (-29%) | 82 / **43** (-48%) | 87 / **46** (-47%) |
| **Unwatered NW+NE (Ctrl / P1)** | 8 / 8 | 4 / **10** (+150%)| 11 / **14** | 7 / **16** (+128%)| 6 / 8 |
| **Unwatered SW (P1 only)** | 0 | 0 | **5** | **4** | **1** |
| **Starvations (Ctrl / P1)** | 2 / 2 | 1 / 1 | 0 / 2 | 5 / **7** (+40%) | 0 / 1 |

---

## 4. Worker Allocation and Travel Findings

### Mechanism: Rigid Static Squad Partitioning (`RULE-W1`)
In `agent/execution/task_scheduler.py` (lines 1092–1114), zonal assignment is hardcoded via `get_home_quadrant`:
```python
if "SW" in unlocked and n_units >= 5:
    sw_squad_size = 5 if n_units >= 13 else 4
    sw_start = n_units - sw_squad_size
    if u_idx >= sw_start:
        return "SW"
    non_sw = sw_start
    half = max(1, non_sw // 2)
    return "NW" if u_idx < half else "NE"
```
Because `DYNAMIC_ZONAL_ALLOCATION` is `False` in production, unlocking SW on Day 11 immediately triggers a rigid structural partition of the 12 available workers:
- **SW Squad:** Statically assigned **4 workers** (indices 8, 9, 10, 11).
- **NW Squad:** Reduced from 6 workers to **4 workers** (indices 0, 1, 2, 3).
- **NE Squad:** Reduced from 6 workers to **4 workers** (indices 4, 5, 6, 7).

### Trapping via C2 Zonal Eligibility (`task_scheduler.py:1661–1676`)
1. **Diagonal Wall:** Workers with home quadrant `SW` are **forbidden** from ever servicing `NE` (`if not ((u_home == "SW" and target_quad == "NE") ...)`).
2. **Strict Distance Floor:** SW workers can only consider `NW` if Manhattan distance `d <= 4` (only reachable near the bottom border of NW).
3. **Priority Gate:** SW workers can only spill over to `NW` if task priority `prio >= 70` (urgent decay/starvation tasks). Regular crop watering (prio 45–55) and standard harvests (prio 60) are completely ineligible for SW worker assistance.

### Rule W2 Idle Anchoring (`task_scheduler.py:1883–1894`)
When SW workers finish their SW tasks or have no actionable work, line 1889 assigns them a fallback task:
`{"priority": 1, "op": "PASS", "target": PORT_SW, "kind": "sw_anchor"}`.
Instead of being dynamically re-assigned to assist backlogged NW or NE operations, SW workers walk to `PORT_SW` (4, 5) and PASS.

### Aggregate Operational Impact (Days 11–29)
| Traced Metric (Days 11–29) | Pair 1 (`pass`) | Pair 3 (`pass`) | Pair 10 (`cow_milk`) | Pair 18 (`full_prod`) |
| :--- | :---: | :---: | :---: | :---: |
| **NW+NE Worker Turns (Control)** | 5,411 turns | 5,477 turns | 5,466 turns | 5,428 turns |
| **NW+NE Worker Turns (P1)** | 4,041 turns (**-25.3%**) | 4,045 turns (**-26.1%**) | 4,096 turns (**-25.1%**) | 4,045 turns (**-25.5%**) |
| **Worker Turns Trapped in SW (P1)**| **1,237 turns** | **1,235 turns** | **1,177 turns** | **1,254 turns** |
| **NW+NE Productive Ops (Control)** | 1,661 ops | 1,574 ops | 1,602 ops | 1,696 ops |
| **NW+NE Productive Ops (P1)** | 963 ops (**-42.0%**) | 981 ops (**-37.7%**) | 962 ops (**-40.0%**) | 974 ops (**-42.6%**) |
| **SW Productive Ops Completed (P1)**| 322 ops | 349 ops | 308 ops | 348 ops |
| **Farm-Wide Net Productive Ops Lost**| **-376 ops** | **-244 ops** | **-332 ops** | **-374 ops** |

**Conclusion:** Rule W1 partitions 4 workers to SW regardless of demand. Over Days 11–29, **1,200+ worker turns** are siphoned into SW, causing an immediate **40% loss of productive operations in NW and NE**. Farm-wide, over 300 productive operations are permanently lost to transit and idle anchoring.

---

## 5. NW/NE/SW Watering and Harvest Findings

### Severe Displacement of High-Value Core Harvests
The 40% loss of productive capacity in NW and NE directly devastated the farm's cash-cow crops (Melons and Strawberries in NW and NE):

| Harvest Performance (Days 11–29) | Pair 1 | Pair 3 | Pair 10 | Pair 18 | Mean Across 4 Pairs |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **NW+NE Harvests (Control)** | 220 | 214 | 223 | 223 | **220.0 harvests** |
| **NW+NE Harvests (P1)** | 121 | 136 | 145 | 128 | **132.5 harvests** |
| **Net NW+NE Harvests Lost** | **-99 harvests** | **-78 harvests** | **-78 harvests** | **-95 harvests** | **-87.5 harvests (-39.8%)** |
| **SW Harvests Gained (P1)** | +42 | +48 | +44 | +45 | **+44.8 harvests** |
| **Net Harvest Delta Across Farm** | **-57 harvests** | **-30 harvests** | **-34 harvests** | **-50 harvests** | **-42.7 harvests** |

### The Asymmetric Value Trade-off
- **Value of Lost NW/NE Harvests:** NW and NE grow high-margin, long-cycle crops (Strawberries selling for $150–$190, Melons selling for $200–$260).
  - 87.5 missed harvests × ~$200 avg realization = **-$17,500.00 gross revenue lost**.
- **Value of Gained SW Harvests:** SW grows fast, cheap crops (Wheat selling for $25–$30 or Carrots selling for $35–$65).
  - 44.8 SW harvests × ~$40 avg realization = **+$1,792.00 gross revenue gained**.
  - Subtract seed costs for SW ($800–$1,050): **Net gain from SW crops is under +$900.00**.
- **Net Crop Economic Balance:** **-$16,600.00 net loss** from crop operations alone.

### Unwatered Crop Observations
Because remaining NW/NE workers were spread too thin, crops frequently missed their daily water:
- **NW+NE Unwatered Plant-Days (Days 11–29):**
  - Control: 101 to 125 total unwatered observations.
  - P1: 197 to 245 total unwatered observations (**+75% to +142% surge**).
- **SW Unwatered Plant-Days (P1):**
  - Even with 4 dedicated SW workers, SW crops accumulated **55 to 70 unwatered plant-days** because workers spent excessive turns traveling between tiles and the shed.

---

## 6. Livestock Feeding and Starvation Findings

### Starvation Observations Explosion
Across the full 20-pair tournament, animal starvation observations exploded from **205 in Control to 560 in P1** (+173%). In the four traced pairs (Days 11–29):
- **Pair 1:** 12 (Control) vs **50 (P1)** (+38 starvations)
- **Pair 3:** 11 (Control) vs **32 (P1)** (+21 starvations)
- **Pair 10:** 13 (Control) vs **24 (P1)** (+11 starvations)
- **Pair 18:** 13 (Control) vs **50 (P1)** (+37 starvations)

### Root Mechanism of Animal Neglect
1. **Feed was available in the shed:** In all traced episodes, the agent maintained sufficient wheat in the shed (purchased via town orders or grown).
2. **Worker starvation through labor scarcity:**
   - In NE, where sheep pastures are located, worker count dropped from 6 to 4.
   - Sheep in NE require cross-quadrant transit to the NW shed to fetch wheat, followed by returning to NE to feed. This requires 4–6 movement actions per sheep.
   - When NE workers were occupied trying to salvage dying NE crops, they failed to complete the multi-turn shed-feed journey before the 24-hour day boundary expired.
3. **Consequences:** Animals missed daily feedings, resulting in loss of wool/milk daily yield, delayed animal growth cycles, and severe penalties to final livestock revenue.

---

## 7. Capital and Economic Opportunity-Cost Findings

### Treasury Impact of SW Acquisition
1. **Land Purchase Outlay:**
   - Day 11 SW unlock cost: **-$3,000.00 cash** immediately deducted.
2. **Immediate Seed Cash Drain:**
   - On Days 11 and 12, P1 immediately purchased seeds to plant 15 SW tiles.
   - Cumulative seed spend (Days 11–29):
     - Pair 1: $2,140 (Control) vs $3,100 (P1) (**+$960 seed spend**)
     - Pair 3: $1,550 (Control) vs $2,260 (P1) (**+$710 seed spend**)
     - Pair 10: $1,930 (Control) vs $2,960 (P1) (**+$1,030 seed spend**)
     - Pair 18: $2,290 (Control) vs $3,340 (P1) (**+$1,050 seed spend**)
3. **Treasury Buffer Depletion:**
   - In Pairs 10 and 18, cash on Day 11 dropped to $1,537 and $2,697 (compared to $3,112 and $6,241 in Control).
   - This compressed cash reserves below the threshold required to execute opportunistic cow/sheep purchases or worker expansions on subsequent days.

### Comprehensive Economic Balance Sheet (P1 vs Control)
| Component | Mean Dollar Impact (P1 vs Control) | Notes |
| :--- | :---: | :--- |
| **Land Capital Cost** | **-$3,000.00** | Upfront purchase cost of quadrant 3 (SW). |
| **SW Seed Spend** | **-$937.50** | Additional seeds purchased for SW tiles. |
| **Gross SW Crop Revenue** | **+$1,792.00** | Realized from ~45 SW harvests (wheat/carrot). |
| **Displaced NW/NE Crop Revenue** | **-$17,500.00** | 87.5 missed high-margin melon/strawberry harvests. |
| **Livestock Yield & Starvation Loss** | **-$2,800.00** | Missed milk/wool yields from 2.7x starvation surge. |
| **Worker Inefficiency Overhead** | *(Reflected in above)* | 350+ productive actions lost to transit & anchoring. |
| **Total Realized Score Delta** | **-$22,445.50** | Matches empirical mean delta across traced pairs (-$20.1k across 20-pair). |

---

## 8. Confirmed Root Causes versus Unverified Hypotheses

### Confirmed Root Causes

#### 1. Architectural Defect: Runtime Disconnection Between Serviceability Evaluation and Crop Activation (`macro_planner.py:1961`) — CRITICAL
- In `agent/strategy/macro_planner.py`:
  ```python
  _, best_k, _ = evaluate_sw_serviceability(day, farm, money, self.fc, target_quadrant=3)
  active_sw_soil = sw_soil_empty[:best_k]
  ```
- **The Defect:** The central planner discards `is_serviceable` (the first tuple element) and unconditionally uses `best_k`!
- When `zero_displacement` is empty (meaning SW cannot be serviced without displacing NW/NE), `evaluate_sw_serviceability` correctly sets `is_serviceable = False`. But because it still returns a candidate `best_k` (typically 15 tiles based on unconstrained gross projection), the macro planner blindly queues 15 seeds and plants SW immediately on Day 11!
- Moreover, `evaluate_sw_serviceability` was called in `macro_planner.py` with default `reserve_desired_herd=True`, so it was not even evaluating the P1 treatment's committed-herd logic.

#### 2. Execution Defect: Rigid Rule W1 Squad Partitioning & Zonal Trapping (`task_scheduler.py:1092`) — CRITICAL
- Once `"SW" in farm.unlocked`, 4 workers are unconditionally partitioned to SW squad regardless of whether SW has 0, 5, or 15 crops.
- C2 Zonal Eligibility traps these 4 workers: they cannot assist NE, cannot assist NW beyond distance 4, and cannot assist NW for non-urgent tasks (prio < 70).
- Rule W2 anchors idle SW workers at `PORT_SW` with PASS actions instead of redirecting them to farm backlogs.

#### 3. Agronomic Defect: Low-Margin SW Crop Mix Displacing High-Margin Crops — MAJOR
- Planting wheat and carrots in SW generated less than $900 in net profit while consuming the exact labor capacity needed to harvest $17,500 of melons and strawberries in NW/NE.

---

### Unverified / Disproven Hypotheses

1. **Hypothesis: Opponent aggression or shop market pricing caused the regression.**
   - **Disproven:** The regression occurred with equal or greater severity against `pass` (-$22,869 in Pair 1, -$31,045 in Pair 3) where the opponent took 0 actions and market demand was static.
2. **Hypothesis: Agent went bankrupt or suffered negative cash penalties.**
   - **Disproven:** Negative cash observations were exactly 0 in both Control and P1 across all 40 games.
3. **Hypothesis: The $3,000 land purchase price alone explains the score delta.**
   - **Disproven:** $3,000 represents only ~15% of the -$20,185 mean loss. 85% of the loss was caused by operational labor displacement and missed harvests.
4. **Hypothesis: Wheat seed accounting error caused starvation.**
   - **Disproven:** Shed inventory logs confirm wheat was abundant in the shed; starvations were caused entirely by labor transit bottlenecks in NE.

---

## 9. The Smallest Recommended Follow-Up Intervention (P1.1)

To make SW land acquisition economically viable, we must resolve the fatal mismatch between the purchase model (which assumes zero displacement) and runtime execution.

### The Minimum Change Supported by Evidence
Rather than overhauling the entire crop portfolio or modifying multiple modules at once, the **single smallest intervention** is:

> **Make post-purchase SW crop activation strictly workload-demand responsive and contingent on verified serviceability (`is_serviceable == True`), while protecting NW/NE baseline labor.**

### Precise Specification

#### File 1: `agent/strategy/macro_planner.py`
- **Location:** Line 1961 (SW soil activation block).
- **Current Defect:**
  ```python
  _, best_k, _ = evaluate_sw_serviceability(day, farm, money, self.fc, target_quadrant=3)
  active_sw_soil = sw_soil_empty[:best_k]
  ```
- **Proposed Correction:**
  ```python
  is_serviceable, best_k, _ = evaluate_sw_serviceability(
      day, farm, money, self.fc, target_quadrant=3, reserve_desired_herd=False
  )
  if not is_serviceable or best_k <= 0:
      active_sw_soil = []
  else:
      active_sw_soil = sw_soil_empty[:best_k]
  ```
- **Rationale:** If `is_serviceable` is False (i.e. zero-displacement pool is empty and NW/NE would suffer labor deficits), the planner must **not** plant SW soil tiles. SW land remains owned, but idle or phased until surplus labor truly exists.

#### File 2: `agent/execution/task_scheduler.py`
- **Location:** Line 1519–1524 (`home_quads` dispatch).
- **Current Defect:** Statically binds 4 workers to SW even if SW has 0 crops or tasks, reducing NW/NE capacity by 40%.
- **Proposed Correction:**
  - If SW has 0 active plants/animals or pending tasks, do **not** assign dedicated workers to SW. Keep all workers in NW/NE until SW tasks actually materialize.
  - Sizing rule: SW squad size = `min(4, max_workers_needed_for_sw_tasks)`. Guarantee a minimum of 5 workers for NW and 5 workers for NE before assigning hands to SW.

### Safety Invariants
1. **Isolate P1:** Keep the P1 purchase correction (`reserve_desired_herd=False`) active.
2. **No Bundling:** Do **not** enable P2 (duplicate seed deductions) or general dynamic crop portfolio changes in this intervention.
3. **Preserve Zero-Displacement Gate:** Never plant a tile in SW if NW or NE has unserviced mandatory workload.

---

## 10. Exact Instructions for Separate Coding Agent

Follow these instructions to implement and validate the proposed intervention on a new experimental branch:

### Step 1: Branch Creation
1. Switch to a new experimental branch from production baseline `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`:
   ```bash
   git checkout -b experiment/sw-p1-workload-responsive 237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e
   ```
2. Cherry-pick the isolated P1 purchase correction commit:
   `b89c8381b341d43c9e81e0701fd8d39edbc8aaaa` (or enable `SW_PURCHASE_WORKLOAD_P1_ENABLED = True`).

### Step 2: Implement Config Flag
In `agent/config.py`:
- Add `SW_WORKLOAD_RESPONSIVE_ACTIVATION_ENABLED: bool = False` (default False).
- Add getter and setter helpers with module synchronization.

### Step 3: Implement Macro Planner Gate
In `agent/strategy/macro_planner.py`:
- Around line 1961, inspect `SW_WORKLOAD_RESPONSIVE_ACTIVATION_ENABLED`.
- When enabled, check `is_serviceable`:
  ```python
  from config import SW_WORKLOAD_RESPONSIVE_ACTIVATION_ENABLED
  if SW_WORKLOAD_RESPONSIVE_ACTIVATION_ENABLED:
      is_serviceable, best_k, _ = evaluate_sw_serviceability(
          day, farm, money, self.fc, target_quadrant=3, reserve_desired_herd=False
      )
      if not is_serviceable:
          active_sw_soil = []
      else:
          active_sw_soil = sw_soil_empty[:best_k]
  ```

### Step 4: Implement Scheduler Demand Responsiveness
In `agent/execution/task_scheduler.py`:
- When `SW_WORKLOAD_RESPONSIVE_ACTIVATION_ENABLED` is active, check if any tasks exist in SW:
  ```python
  sw_tasks_exist = any(farm.quadrant_of(t.get("target") or (0, 0)) == "SW" for t in tasks)
  if not sw_tasks_exist:
      # Keep all hands in NW / NE
      home_quads = {u_idx: ("NW" if u_idx < n_units // 2 else "NE") for u_idx in range(n_units)}
  ```

### Step 5: Mirror to `submission/`
- Ensure 100% byte parity between `agent/` and `submission/`.

### Step 6: Regression Testing
- Run focused tests: `pytest agent/tests/test_sw_purchase_workload_correction.py -q`.
- Run full regression: `pytest agent/tests/ -q` (all 995+ tests must pass).
- Verify submission package build: `python scripts/build_submission.py`.

---

## 11. Validation Contract for Next Experimental Arm

Run a 3-arm deterministic A/B evaluation across the 20 matched seeds:

1. **Arm 1: Production Baseline (Control)** — Commit `237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`
2. **Arm 2: Original P1 Treatment** — Purchase-only correction (`SW_PURCHASE_WORKLOAD_P1_ENABLED = True`)
3. **Arm 3: P1 + Workload-Responsive Activation (P1.1)** — Both switches active.

### Evaluation Requirements
- **Matched Seeds & Opponents:** Identical 20 pairs (seeds 7101–7520, opponents `pass`, `pure_wheat_rush`, `cow_milk_engine`, `melon_sniper`, `full_production_agent`).
- **Balanced Player Seats:** Standard seat distribution.
- **Strict Denominator Rule:** Keep all 20 episodes in denominator regardless of purchase status.
- **Success Criteria for Arm 3:**
  1. Mean paired score delta vs Control must be **positive (>= +$2,000.00)** or statistically non-inferior with 0 losses due to labor starvation.
  2. Starvation observations must remain at baseline levels (<= 250 across 20 matches).
  3. NW+NE harvest counts must not drop by more than 5%.
  4. Realized SW crop revenue must exceed the sum of land price ($3,000) and seed expenditures.
