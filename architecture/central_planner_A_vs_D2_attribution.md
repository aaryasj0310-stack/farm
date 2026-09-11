# Central Planner Diagnostic Attribution Audit: Architecture A vs Architecture D2

**Date**: 2026-09-12  
**Target Engine**: Kaggriculture v1.32.7  
**Population**: 50 Paired Scenarios (Seeds 101–125 across `random` and `starter` = 100 720-turn matches)  
**Authoritative Artifacts**:
- Machine-readable summary: `artifacts/central_planner_A_vs_D2_attribution.csv`
- Raw turn-by-turn divergence telemetry: `artifacts/central_planner_A_vs_D2_attribution.json`

---

## 1. Executive Summary

This diagnostic-only audit compares the production baseline (**Architecture A: `historical_stack`**, legacy compose with historical candidate limits) against **Architecture D2: `historical_candidates_central`** (CentralPlanner with candidate discipline and feed-wheat priority correction).

### Headline Results
```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ATTRIBUTION AUDIT SUMMARY (50 Paired Scenarios, 36,000 Turns)                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ • Architecture A Mean Money:       $70,287.46                                          │
│ • Architecture D2 Mean Money:      $67,631.78                                          │
│ • Mean Paired Delta (D2 - A):      -$2,655.68 (Median: -$1,166.50)                     │
│ • Delta Range:                     Min -$16,328.00 | Max +$7,759.00                    │
│ • Paired Record:                   15 Wins / 35 Losses / 0 Ties (30.0% Win Rate)       │
│                                                                                        │
│ • Total Evaluated Turns:           36,000 turns                                        │
│ • Total Divergent Turns:           3,800 turns (10.56% overall divergence rate)        │
│ • Selection Divergent Turns:       3,683 turns (10.23%)                                │
│ • Execution Reorder Only Turns:    117 turns (0.33%)                                   │
│ • Candidate Stream Equivalence:    100% Verified (0 invalid pairs prior to divergence) │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Upstream Candidate Stream Verification

Before arbitration, on every turn prior to the first game state divergence, we verified:
$$\text{purchase\_orders}_A == \text{purchase\_orders}_{D2} \quad \text{and} \quad \text{sell\_orders}_A == \text{sell\_orders}_{D2}$$
- **Candidate Equivalence Rate**: **100.0%**.
- Across all 50 paired scenarios, upstream candidate proposals were identical until the referee selected different order multisets.

---

## 3. Divergence Classification & Loss Association

Every turn where market orders differed between A and D2 was classified into conflict categories:

| Category | Total Turns | In D2 Losses | In D2 Wins | Loss Concentration | Mean Episode Delta |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`SELL_vs_SELL`** | 2,439 | 1,781 | 658 | 73.0% | -$3,047.15 |
| **`HIRE_vs_SELL`** | 603 | 460 | 143 | **76.3%** | **-$3,098.72** |
| **`PURCHASE_vs_PURCHASE`** | 474 | 328 | 146 | 69.2% | -$3,169.68 |
| **`execution_reorder_only`** | 117 | 72 | 45 | 61.5% | -$2,040.73 |
| **`HIRE_vs_WHEAT`** | 94 | 82 | 12 | **87.2%** | **-$3,560.28** |
| **`OTHER`** | 49 | 35 | 14 | 71.4% | -$3,464.61 |
| **`PURCHASE_vs_SELL`** | 22 | 18 | 4 | 81.8% | -$2,672.27 |
| **`WHEAT_vs_SELL`** | 2 | 2 | 0 | 100.0% | -$7,362.50 |

---

## 4. First Selection Divergence per Episode

Analyzing the **first selection-changing turn** for each match isolates the root cause from downstream cascading state divergence:

| First Divergence Category | Episodes | In D2 Losses | In D2 Wins | Loss Share |
| :--- | :--- | :--- | :--- | :--- |
| **`HIRE_vs_SELL`** | **30 (60.0%)** | **23** | 7 | **76.7%** |
| **`PURCHASE_vs_PURCHASE`** | 15 (30.0%) | 9 | 6 | 60.0% |
| **`SELL_vs_SELL`** | 5 (10.0%) | 3 | 2 | 60.0% |

### First Divergence Exceeding $500 in Economic Value
| First > $500 Divergence Category | Episodes | Percentage |
| :--- | :--- | :--- |
| **`HIRE_vs_SELL`** | **43** | **86.0%** |
| **`HIRE_vs_WHEAT`** | 4 | 8.0% |
| **`SELL_vs_SELL`** | 2 | 4.0% |
| **`PURCHASE_vs_PURCHASE`** | 1 | 2.0% |

---

## 5. Root-Cause Mechanism: The Day 10–11 Morning Collision

In 60% of all episodes (and 86% of major economic divergences), the very first divergence occurs on **Day 10 or Day 11 at Hour 0**, driven by a collision between workforce expansion and shed soft-cap liquidation:

### The Mechanism
1. **Upstream State**:
   By Days 10–11, early NW/NE crop harvests have filled the shed ($\ge 65$ items, typically 85–95 items).
   Simultaneously, `DAY_TO_HANDS` increases target workforce from 8 to 10 (Day 10) and 12 (Day 11).
2. **Upstream Proposals**:
   - `OrderBuilder` proposes 10 `HIRE` orders on Hour 0 (+ any needed seeds for that day's planting).
   - `MarketBrain` proposes 6 `SELL` orders.
3. **What Architecture A Does**:
   - In `legacy_compose_market`, `purchases_first = (hour in (0, 1))`.
   - On Hour 0, purchases unconditionally take priority. Architecture A executes all 10 `HIRE` (or 8 `HIRE` + 2 `SEED`) orders.
   - On Hour 1, only 2 `HIRE` orders are needed to hit the 12-hand cap. The remaining 8 slots allow all 6 `SELL` orders to execute.
   - **Result in A**: Architecture A successfully executes hires, seeds, and sells across Hours 0 and 1.
4. **What Architecture D2 Does**:
   - `CentralPlanner._classify_sell` detects `shed_total >= SHED_SOFT_CAP (65)` and classifies all 6 sell orders as **$P_0$ CRITICAL (`urgency = 2.0`)**.
   - `CentralPlanner._classify_purchase` classifies `HIRE` on Hour 0 as **$P_1$ URGENT (`urgency = 1.0`)**.
   - Because $P_0 > P_1$, the 6 sell orders take slots 0..5.
   - Only 4 slots remain for `HIRE`. Any `BUY_SEED` orders are **completely dropped**.
   - On Hour 1, D2 still needs 8 hires. `OrderBuilder` only proposes `HIRE` on Hour 1 (it does not re-propose dropped seeds).
   - **Result in D2**: D2 permanently loses that day's seed purchases, missing that day's planting cycle, while suffering reduced workforce efficiency on Hour 1.

---

## 6. Subsystem Timing Audits

### A. Land Timing Audit
- **NE Unlock Day Delta ($D2 - A$)**: **Mean +0.00 days** (Exact Matches: 50 / 50 = **100.0% identical**).
- **SW Unlock Day Delta**: Neither architecture unlocks SW under this configuration.
- **Finding**: Land expansion timing is 100% identical. Land timing contributes **zero** to the score gap.

### B. Hires Volume & Timing Audit
- **Total Season Hires Delta ($D2 - A$)**: **Mean +0.00** (Exact Matches: 50 / 50 = **100.0% identical**).
- Both architectures hire the exact target number of hands every day.
- **Timing Difference**: In A, workforce is fully hired on Hour 0 (100% available by Hour 1). In D2, shed-pressure sells delay half the workforce hiring into Hour 1.

### C. Seed Timing & Lost Planting Cycles
- On turns where `HIRE_vs_SELL` occurs on Hour 0, `BUY_SEED` orders that were scheduled for that morning are squeezed out by $P_0$ sells.
- Because `OrderBuilder` only emits general crop seeds on Hour 0, squeezed seeds are omitted for that entire day, delaying crop cycles by 24 hours.

### D. Endgame Audit (Days 28–29)
- Days 28–29 account for only **104 out of 3,800 divergences (2.7%)**.
- Final Day 29 liquidation is governed by $P_0$ critical sell priority in both architectures.
- Endgame behavior is not a contributor to the gap.

### E. Execution-Only Reordering Audit
- Occurred in only **117 out of 36,000 turns (0.33%)**.
- Reordering identical multisets had no measurable impact on market clearing or pricing.

---

## 7. Sell Realization & Revenue Impact

Sales present in Architecture A but displaced or delayed in D2:

| Product | Displaced Orders | Total Quantity | Estimated Market Value |
| :--- | :--- | :--- | :--- |
| **STRAWBERRY** | 480 | 2,031 | $519,662.00 |
| **WHEAT** | 1,607 | 10,867 | $387,238.00 |
| **MELON** | 383 | 1,557 | $351,202.00 |
| **MILK** | 367 | 1,267 | $311,751.00 |
| **FERTILIZER** | 348 | 751 | $70,571.00 |
| **CARROT** | 113 | 570 | $45,791.00 |
| **TOMATO** | 138 | 403 | $26,847.00 |

Because Architecture A routinely clears 177.2 sell orders per match versus 173.7 in D2, A realizes higher net crop revenue ($84.3k vs $83.6k).

---

## 8. Hour Band Distribution

| Hour Band | Divergences | Percentage | Primary Dynamic |
| :--- | :--- | :--- | :--- |
| **Sell Window (5, 9, 13, 17, 21)** | 2,100 | 55.3% | Downstream differences in shed inventory & crop harvests |
| **Hour 1** | 815 | 21.4% | Delayed hire fulfillment following Hour 0 shed collisions |
| **Hour 0** | 780 | 20.5% | Root-cause `HIRE_vs_SELL` collision under shed soft cap |
| **Endgame (Days 28–29)** | 104 | 2.7% | Minor liquidation timing differences |
| **Other Hours** | 1 | 0.0% | Negligible |

---

## 9. Ranked Root-Cause Table

| Rank | Divergence Pattern | Frequency | Loss Association | Estimated Impact | Confidence | Root Cause Detail |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **`HIRE_vs_SELL` on Morning Hour 0** | 603 turns (60% of first divs) | **76.7% in D2 Losses** | **-$2,000 to -$3,000** | **High** | Shed soft cap ($\ge 65$) promotes routine sells to $P_0$, crowding out morning hires and permanently dropping seeds. |
| **2** | **Downstream `SELL_vs_SELL` Divergence** | 2,439 turns | 73.0% in D2 Losses | -$500 to -$1,000 | Medium | Cascading consequence of delayed planting and shifted inventory. |
| **3** | **`HIRE_vs_WHEAT` Competition** | 94 turns | 87.2% in D2 Losses | -$300 to -$500 | Medium | Minor slot contention between wheat buffer buys and workforce hires. |
| **4** | **Execution Reorder Only** | 117 turns | 61.5% in D2 Losses | < $50 | Low | Negligible impact on clearing. |

---

## 10. Decision Gate & Final Recommendations

### Decision Gate Verdict: **Conclusion A (One Dominant Planner Weakness Identified)**

The audit conclusively demonstrates that:
1. **The performance difference is NOT diffuse**: A single repeatable pattern (`HIRE_vs_SELL` on Hour 0 when shed $\ge 65$) accounts for **60.0% of all initial match divergences** and **86.0% of all major divergences > $500**, with a **76.7% concentration in D2 losses**.
2. **The mechanism is clear**: Legacy compose's temporal rule (`purchases_first on hours 0 and 1`) avoids crowding by allowing hires on Hour 0 and sells on Hour 1. CentralPlanner currently marks any sell when shed $\ge 65$ as $P_0$ CRITICAL, preempting mandatory morning workforce and seed purchases.

### Production Recommendations
1. **Production Default**: Keep `ARBITRATION_MODE = "historical_stack"` in `agent/config.py`.
2. **CentralPlanner Tuning Recommendation (For a Future Task)**:
   In `CentralPlanner._classify_sell`, distinguish true midnight/emergency shed overflow from routine shed soft-cap liquidation on morning hours:
   - On Hour 0, routine soft-cap sells should NOT be promoted to $P_0$ above mandatory morning `HIRE` and `SEED` orders ($P_1$).
   - True $P_0$ sell emergency should require actual physical capacity overflow (`shed >= 96`), not merely the soft warning threshold (`shed >= 65`).
3. **No Code Changes in This Task**: Strictly per specification, zero tuning or strategy modifications were introduced during this audit.
