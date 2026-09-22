# Kaggriculture P3.2 — State-Dependent Animal Care Results & Evaluation

## 1. Executive Summary

Phase **P3.2 (State-Dependent Animal Care Urgency)** tested whether selectively escalating high-value animal care (`COW` and `SHEEP`) above routine crop bonus watering could recover the static modeled loss of **$3,926.00/game**.

### Key Statistical Results (A/B Tournament Evaluation)
- **Control Baseline (`536f1e7`) Mean**: **$106,361.60**
- **Treatment (`P3.2`) Mean**: **$102,906.75**
- **Mean Paired Delta**: **-$3,454.85/game**
- **Median Paired Delta**: **-$1,877.50/game**
- **95% Confidence Interval**: **[$-6,545.56, $-364.14]** (Entire interval is strictly negative!)
- **Paired t-statistic**: **t = -2.2356, p = 0.0375** (Statistically significant regression at $p < 0.05$)
- **Record (W / L / T)**: **4W / 16L / 0T (20.0% Win Rate / 80% Loss Rate)**
- **Decision**: **DECISIVELY REJECT P3.2**.

---

## 2. Telemetry & Root Cause Analysis

### Physical Mechanism Reconciliation
```
Metric                       Control (`536f1e7`)   Treatment (`P3.2`)       Delta
-----------------------------------------------------------------------------------------
CARE Actions / Game                 193.9                202.6              +8.7 cares
Animal Revenue / Game            $5,411.25            $5,497.50             +$86.25
Missed Water Bonus / Game            84.4                 88.5              +4.1 missed
Final Score / Game             $106,361.60          $102,906.75           -$3,454.85
```

### Why P3.2 Caused a Severe Score Regression
1. **Negligible Realized Animal Value (+8.7 Cares = +$86.25 Revenue)**:
   - Baseline already achieves a **90.5% care completion rate** (202.1 cares completed out of 223.2 animal-days).
   - In the engine, `interval = 2` (Cow) and `interval = 3` (Sheep) cap the maximum bankable bonus per cycle.
   - Forcing +8.7 extra care actions per game increased animal revenue by only **+$86.25/game**.
2. **Disruption of Crop Watering Sweeps (+4.1 Missed Bonus Waters)**:
   - Crop fields are concentrated in the NW and NE core. A worker can water 5–6 contiguous crops in consecutive turns with near-zero transit.
   - Pastures are located on peripheral tiles.
   - Elevating CARE from priority 65 to 72/74 (above `PRIORITY_BONUS_WATER = 70`) pulled workers out of active watering sweeps to walk across the farm to pet cows.
   - This caused +4.1 missed watering bonuses per game. Missing watering bonuses on crops delays harvest windows, reduces yield, and snowballs into delayed liquidity and fewer livestock purchases.
3. **Severe Asymmetry of Opportunity Cost**:
   - Gaining +$86.25 in animal revenue cost thousands of dollars in disrupted crop timing and wasted worker movement turns.

---

## 3. Reconciling the Static $3,926 Loss Estimate

The diagnostic telemetry decisively reconciles the original static audit estimate:
- **Original Static Estimate**: $3,926.00/game
- **Unrealizable Misses**:
  - $480/game from unfed animals (care banks $0 if unfed)
  - $1,000/game from cycle saturation (bank already full)
  - $152/game from endgame cutoff (Days 28–29 produce after Day 30)
- **Net Recoverable Opportunity**: At most $1,632.50/game
- **Realized Result**: **-$3,454.85/game** due to spatial disruption of crop sweeps.
- **Conclusion**: Baseline animal care scheduling (`PRIORITY_CARE_ANIMAL = 65`) is already near-optimal. Animal care should NEVER outrank crop watering sweeps.

---

## 4. Final Decision & Lineage State

- **Decision**: **REJECT P3.2**.
- **Lineage**: Repository strictly maintained at promoted baseline [`536f1e7071eaa9cdb0f1f3bdb733dce7f75ee77e`](file:///d:/website%20project/kaggri%20ox). `git diff` is completely clean.
- **Roadmap to $130,000**:
  - Both P3.1 (Harvest Priority) and P3.2 (Care Priority) have proven that manipulating task priority bands within the existing spatial paradigm creates negative secondary displacements.
  - The dominant unrecovered loss is **avoidable transit movement (64.5% of all turns, 4,763 steps/game)**.
  - Next Phase: **P3.3 — Spatial Locality & Route Compaction** (reducing avoidable transit without rigid quadrant lock-in).
