# P5.0-R Reclassified Wheat Events: Empirical Results & Verification

## 1. Overview & Dataset Scope

All 100 discovery games on seeds `96,201–96,210` ($\times 5\text{ opponents} \times 2\text{ seats}$) were audited under authoritative baseline configuration (`536f1e7`). 

Every single Day 21–25 wheat planting decision was captured as a complete state snapshot (cash, inventories, worker positions, in-ground crops, placed livestock, and market prices) and evaluated through the Time-Indexed Dynamic Feed Security Ledger.

A total of **2,493 wheat planting events** were evaluated (averaging **24.93 decisions per game**).

---

## 2. Classification Summary

| Classification Code | Meaning | Count | Per-Game Rate | Percentage |
| :--- | :--- | :---: | :---: | :---: |
| **RW1** | **Feed Critical (Deficit on Day $\le 28$)** | **0** | **0.00** | **0.0%** |
| **RW2** | **Feed Buffer Support ($0 \le B_{\min} < \beta$)** | **4** | **0.04** | **0.2%** |
| **RW3** | **Genuine Economic Surplus ($B_{\min} \ge \beta$)** | **2,489** | **24.89** | **99.8%** |
| **RW4** | **Terminal Non-Maturing ($D \ge 26$)** | **0** | **0.00** | **0.0%** |
| **Total** | All Day 21–25 Wheat Decisions | **2,493** | **24.93** | **100.0%** |

### Key Empirical Findings:
1. **Zero Feed Critical Events (RW1 = 0)**:
   In the 100 discovery games, not a single wheat planting on Days 21–25 was required to avoid herd starvation. The farm's existing liquid grain and maturing early-season wheat crops are so abundant that removing any individual Day 21–25 wheat planting leaves future feed non-negative throughout the season.
2. **Extreme Surplus Dominance (RW3 = 99.8%)**:
   2,489 out of 2,493 plantings are genuine economic surplus. The farm had already secured not only enough feed to avoid starvation, but maintained a buffer exceeding 1 full animal-day of feed reserves.
3. **The 4 RW2 Events**:
   Only 4 events fell into the RW2 buffer support category (3 against `pure_wheat_rush`, 1 against `full_production_agent`, all on Day 21). In these 4 rare instances, the farm had slightly smaller reserves at the moment of planting, so removing wheat dipped the projected minimum buffer below $\beta$.

---

## 3. Breakdown by Day of Season

| Day | Total Decisions | RW3 (Surplus) | RW2 (Buffer) | RW1 (Critical) | RW3 % |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Day 21** | 418 | 414 | 4 | 0 | 99.0% |
| **Day 22** | 388 | 388 | 0 | 0 | 100.0% |
| **Day 23** | 460 | 460 | 0 | 0 | 100.0% |
| **Day 24** | 656 | 656 | 0 | 0 | 100.0% |
| **Day 25** | 571 | 571 | 0 | 0 | 100.0% |
| **Total** | **2,493** | **2,489** | **4** | **0** | **99.8%** |

Notice that planting volume increases substantially on Days 24–25 (1,227 total decisions, 49.2% of all late wheat). This surge occurs because early-season strawberry and tomato beds are cleared and harvested around Day 23–24, leaving core tiles empty. Under baseline logic, `macro_planner` blindly refills these tiles with wheat.

---

## 4. Breakdown by Opponent

| Opponent Agent | Games | Total Decisions | Decisions/Game | RW3 Count | RW2 Count |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `melon_sniper` | 20 | 503 | 25.15 | 503 | 0 |
| `cow_milk_engine` | 20 | 526 | 26.30 | 526 | 0 |
| `pass` | 20 | 500 | 25.00 | 500 | 0 |
| `pure_wheat_rush` | 20 | 459 | 22.95 | 456 | 3 |
| `full_production_agent` | 20 | 505 | 25.25 | 504 | 1 |
| **Total** | **100** | **2,493** | **24.93** | **2,489** | **4** |

The rate of late wheat planting is exceptionally stable across all 5 opponents (between 22.95 and 26.30 decisions/game), confirming that late wheat replanting is an endogenous artifact of baseline internal tile management, not an opponent-reactive behavior.

---

## 5. Breakdown by Seat Position

| Seat | Games | Total Decisions | Decisions/Game | RW3 Count | RW2 Count |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Seat 0 (First Player)** | 50 | 1,255 | 25.10 | 1,252 | 3 |
| **Seat 1 (Second Player)** | 50 | 1,238 | 24.76 | 1,237 | 1 |
| **Total** | **100** | **2,493** | **24.93** | **2,489** | **4** |

Seat parity is virtually identical (25.10 vs 24.76 decisions/game), verifying that player order introduces no material bias into late-wheat surplus generation.
