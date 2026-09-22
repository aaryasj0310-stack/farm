# Kaggriculture P5.1-C — Two-Cycle Rotation Execution & Profitability Audit

## 1. Executive Summary

This report analyzes the micro-execution rates, transition failure points, and standalone vs system-wide profitability of the P5.1 Two-Cycle Carrot Rotation across all 100 matched pairs (200 live games).

### Key Audit Metrics:
- **Total Tracked Rotation Candidates**: 1,637 tiles (16.37 tiles / game).
- **Completed Two-Cycle Rotations**: **626 rotations** (38.2% completion rate; 6.26 completed / game).
- **Day-23 Initiated Completed Rotations**: **211 rotations** (33.7% of all completed rotations).
- **Cycle 1 (C1) Plantings**: **956 plantings** (58.4% of tracked tiles).
- **Cycle 2 (C2) Plantings**: **648 plantings** (67.8% of C1 plantings; 39.6% of tracked tiles).
- **Failed Rotation Attempts**: **1,011 tiles** (61.8% failure rate).

---

## 2. Failure Mode Decomposition

Every failed rotation candidate was categorized by its exact transition drop point:

| Failure Reason | Occurrence Count | Percentage of Failures | Primary Mechanism |
| :--- | :---: | :---: | :--- |
| **C1 plant missed on Day 23** | 298 | 29.5% | Competing wheat planting tasks or seed pre-order latency |
| **C1 plant missed on Day 21** | 237 | 23.4% | Core farm tile not cleared or worker dispatch delay |
| **C2 replant deadline missed (D25 H18)** | 190 | 18.8% | C1 harvest delayed past Hour 18 or worker busy with strawberries |
| **C1 plant missed on Day 22** | 168 | 16.6% | Worker assigned to livestock care instead of planting |
| **C2 replant deadline missed (D26 H18)** | 66 | 6.5% | Shed seed fetch blocked or path congestion |
| **C2 replant deadline missed (D27 H18)** | 52 | 5.1% | Final replant window elapsed |
| **Total Failed Rotations** | **1,011** | **100.0%** | — |

### Causal Insight:
- **703 failures (69.5%) occurred during C1 initiation**: The agent's central planner frequently had competing tasks (such as wheat planting or livestock care) that overrode or delayed the C1 carrot planting on Days 21–23.
- **308 failures (30.5%) occurred during the C2 replant window**: Even when C1 was planted and harvested, workers often failed to return with C2 seeds before the strict Hour 18 replanting deadline. Tiles that missed C2 remained barren or fell back to low-yield late plantings.

---

## 3. Micro-Economics: Isolated Mirage vs Whole-Farm Reality

### 3.1 The Isolated Rotation Ledger (Theoretical Model)
In isolation, a single completed two-cycle carrot rotation appears highly profitable:
- **Revenues**:
  - Cycle 1 (3 carrots @ $42.09): $126.27
  - Cycle 2 (3 carrots @ $42.09): $126.27
  - Total Revenue: **$252.54**
- **Direct Costs**:
  - Cycle 1 Seed: $20.00
  - Cycle 2 Seed: $20.00
  - Total Seed Cost: **$40.00**
- **Net Isolated Margin**: **+$212.54 per completed rotation**.

### 3.2 The Wheat Opportunity Cost
The same tile in baseline grew wheat planted on Days 21–23 and harvested on Days 25–27:
- **Baseline Yield**: 3.72 wheat units @ $36.56 average price = **$136.00**.
- **Wheat Seed Cost**: **$10.00**.
- **Net Baseline Margin**: **+$126.00 per tile**.
- **Modeled Direct Gain from Substitution**:
  $$\$212.54 - \$126.00 = \mathbf{+\$86.54 \text{ per completed rotation}}$$

Across 6.26 completed rotations per game, this generated the **+$541.74** theoretical lift that originally inspired P5.1.

### 3.3 The Whole-Farm Reality (General Equilibrium)
However, in live game execution, four destructive systemic costs completely reversed this gain:

1. **The Incomplete Rotation Penalty (−$115 / game)**:
   Across the 10.11 failed attempts per game, tiles were taken out of the baseline wheat schedule but failed to complete C2. Many grew only C1 (+3 carrots, −$20 seed = +$106 net) while forfeiting baseline wheat (+$126 net), creating an immediate **−$20 loss per incomplete tile**.
2. **Forced Market Feed Purchases (−$559.88 / game)**:
   Homegrown wheat costs $10 in seed. When 41.84 wheat units were displaced, the livestock engine purchased replacement wheat from the open market at an average price of **$36.91 / unit**. This substitution incurred an immediate price penalty of:
   $$41.84 \times (\$36.91 - \$10.00) = \mathbf{-\$1,125.91 \text{ gross feed penalty}}$$
   (Offset partially by wheat sold on market).
3. **Livestock Care Bonus Voiding (−$985.32 / game)**:
   The physical absence of grain in the shed caused workers to skip 3.24 feedings, voiding care bonuses on cows and sheep and destroying 2.50 milk units and 1.91 wool units.

### Balance Sheet Summary:
| Level of Analysis | Metric | Net Delta / Game |
| :--- | :--- | :---: |
| **Isolated Carrots** | Gross Carrot Margin (Rev − Seeds) | **+$1,269.96** |
| **Crop General Equilibrium** | Forfeited Wheat Sales + Wheat Seed Saved | **−$822.63** |
| **Farm Logistics Equilibrium** | Forced Market Feed Wheat Purchases | **−$559.88** |
| **Systemic Farm Profit** | **Net Crop & Feed Impact** | **−$112.55** |
| **Livestock Externality** | Voided Care Bonuses (Milk, Wool, Fertilizer) | **−$985.32** |
| **Labor Disruption** | Extra Labor Hires & Discarded Overflows | **+$77.19** |
| **TOTAL TOURNAMENT DELTA** | **Reconciled Cash Deficit** | **−$1,020.68** |

### Conclusion:
The two-cycle carrot rotation was fundamentally uneconomic because it traded high-leverage input grain ($10 seed producing feed for $244 milk) for standalone cash crops ($42 carrots) on a farm constrained by shed storage and intraday logistics.
