# Kaggriculture P5.1 — 100-Pair Live Discovery Replay Results

## 1. Executive Summary

This report documents the empirical results of the **P5.1 Two-Cycle Carrot Rotation Live Discovery Replay**, evaluating the isolated treatment of substituting surplus Day 21–23 wheat plantings on NW+NE core tiles with two consecutive carrot cycles under state-based sequential feed safety guarantees.

The discovery panel was tested across **100 matched pairs (200 live games)** on discovery seeds `96,201–96,210`, spanning all 5 benchmark opponents across both player seats (P0 and P1).

### Key Empirical Findings:
1. **Execution Mechanics Fully Succeeded**:
   - The state machine, seed pre-ordering, and priority protection completely solved the previous Cycle 2 execution bottleneck.
   - **626 two-cycle carrot rotations** were completed across 100 games (mean **6.26 completed rotations/game**).
   - Once Cycle 2 was planted, **96.60%** successfully completed to final harvest.
   - Day 23 plantings successfully executed all the way to Day 29 harvest (**211 Day 23 rotations completed**, mean 2.11/game).
2. **Feed Safety Maintained at 100%**:
   - Zero animal starvations occurred across all 100 treatment games (**0.0% starvation rate**). The state-based sequential feed ledger prevented any feed deficit.
   - Win rate remained **100.0%** in both Control and Treatment.
3. **Economic Live Delta is Strongly Negative**:
   - **Mean Paired Cash Delta**: **−$1,020.68 / game**
   - **Median Paired Cash Delta**: **−$959.00 / game**
   - **95% Confidence Interval**: **[−$1,578.80, −$462.56]** (statistically significantly negative, $p < 0.001$)
   - 36 pairs finished positive, 63 pairs finished negative, and 1 pair tied.

---

## 2. Statistical Distribution of Paired Cash Deltas

$$\Delta \text{Money} = \text{Money}_{\text{treatment}} - \text{Money}_{\text{control}}$$

| Metric | Empirical Value |
| :--- | :--- |
| **Matched Pairs ($N$)** | 100 (200 full simulation games) |
| **Elapsed Runtime** | 1,258.7 s (20.98 minutes, 8 parallel workers) |
| **Mean $\Delta \text{Money}$** | **−$1,020.68 / game** |
| **Median $\Delta \text{Money}$** | **−$959.00 / game** |
| **Standard Deviation ($\sigma$)** | $2,847.55 |
| **Standard Error ($SE$)** | $284.76 |
| **95% Confidence Interval** | **[−$1,578.80, −$462.56]** |
| **Min $\Delta \text{Money}$** | −$8,271.00 (Seed 96206 vs `pure_wheat_rush` S1) |
| **Max $\Delta \text{Money}$** | +$6,470.00 (Seed 96208 vs `pure_wheat_rush` S1) |
| **Positive / Negative / Zero** | 36 positive / 63 negative / 1 zero |
| **Control Win Rate** | 100.0% (100 / 100) |
| **Treatment Win Rate** | 100.0% (100 / 100) |
| **Treatment Starvations** | **0 (0.0%)** |

---

## 3. Breakdown by Opponent

The 100 matched pairs are evenly partitioned into 20 pairs per opponent (10 seeds × 2 seats):

| Opponent | n | Mean $\Delta \text{Money}$ | Median $\Delta \text{Money}$ | Positive Pairs | Negative Pairs | Win Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `pass` | 20 | −$253.05 | +$338.00 | 11 | 9 | 100% |
| `pure_wheat_rush` | 20 | −$242.50 | +$776.00 | 11 | 9 | 100% |
| `melon_sniper` | 20 | −$787.05 | −$1,162.00 | 6 | 14 | 100% |
| `cow_milk_engine` | 20 | −$1,649.35 | −$1,117.00 | 6 | 14 | 100% |
| `full_production_agent` | 20 | **−$2,171.45** | **−$1,865.00** | 2 | 17 (1 tie) | 100% |

### Opponent Insights:
- Against passive or one-dimensional crop opponents (`pass`, `pure_wheat_rush`), medians are mildly positive (+**$338** and +**$776**), but heavy negative outliers pull means negative.
- Against competitive, livestock-heavy, or high-efficiency baselines (`cow_milk_engine`, `full_production_agent`), performance degrades severely (means of **−$1,649.35** and **−$2,171.45**). Against `full_production_agent`, 17 out of 20 pairs underperformed the baseline.

---

## 4. Breakdown by Seat

| Seat | n | Mean $\Delta \text{Money}$ | Median $\Delta \text{Money}$ |
| :--- | :---: | :---: | :---: |
| **Seat 0 (P0)** | 50 | −$1,224.30 | −$959.00 |
| **Seat 1 (P1)** | 50 | −$817.06 | −$873.00 |

Both seats exhibit substantial, statistically significant underperformance, demonstrating that the negative delta is not an artifact of turn-order priority.

---

## 5. Two-Cycle Execution & Feasibility Metrics

| Pipeline Stage | Total Observed Count | Per Game Mean | Conversion Rate |
| :--- | :---: | :---: | :---: |
| **Evaluated Opportunities** | 1,659 | 16.59 | 100.0% |
| **Cycle 1 Planted** | 956 | 9.56 | 57.62% of evaluated |
| **Cycle 2 Planted** | 648 | 6.48 | 67.78% of C1 planted |
| **Two-Cycle Rotations Completed** | **626** | **6.26** | **96.60% of C2 planted** (65.48% of C1) |
| **Day 23 Completed Rotations** | **211** | **2.11** | **33.71% of all completed** |

### Execution Conclusions:
1. **The Execution Mechanism is Completely Sound**:
   - The agent successfully executed 626 full two-cycle rotations across 100 games.
   - The drop from C1 (956) to C2 (648) occurred primarily because tiles planted on Day 21/22 occasionally suffered weather delays or the tile was dynamically reclaimed by macro priorities on Day 25/26.
   - Crucially, once Cycle 2 was planted, **96.60% (626 / 648)** reached full maturity and were successfully harvested.
2. **Day 23 Feasibility Confirmed**:
   - 211 full Day 23 → Day 26 → Day 29 cycles completed across the 100 games.
   - Day 23 carrot planting is physically and mechanically feasible within the game engine.

---

## 6. Comparison with Pre-Implementation Smoke Gate

| Gate Metric | Smoke Gate (Seed 96201 vs Pass) | Full Discovery (100 Pairs, 200 Games) | Status |
| :--- | :---: | :---: | :---: |
| **Completed Rotations** | 5 (target $\ge 5$) | 626 (6.26 / game) | PASS |
| **D23 Completed** | 1 (target $\ge 1$) | 211 (2.11 / game) | PASS |
| **Starvation Rate** | 0.0% (target 0.0%) | 0.0% (0 / 100 games) | PASS |
| **Mean Cash Delta** | +$3,114.00 | **−$1,020.68** | **FAIL** |

While the smoke test on seed 96201 against `pass` was an anomalous positive outlier (+**$3,114.00**), the full 100-pair matched panel conclusively reveals that the general population outcome of substituting wheat with 2-cycle carrots is negative.
