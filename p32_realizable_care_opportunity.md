# Kaggriculture P3.2 — Realizable Animal Care Opportunity Audit

## 1. Executive Summary

In the initial static labor audit (`p3_execution_loss_decomposition.md`), animal care losses were estimated at **$3,926.00/game**.
Following the instructions of Kaggriculture P3.2 Phase 2, a 20-game telemetry audit across seeds 90,001–90,010 was conducted to categorize every missed care opportunity into categories **C1 through C7** based on ground-truth engine realizability.

### Primary Audit Findings
- **Total Animal Days / Game**: **223.2**
- **Completed CARE Actions / Game**: **202.1** (90.5% completion rate in baseline)
- **Total Missed CARE Actions / Game**: **21.1 actions/game**
- **Unrealizable Missed Care (C2 + C3 + C4 + C6)**: **10.40 actions/game** (49.3% of all misses, **$0.00** economic value)
- **Realizable Missed Care (C1)**: **10.70 actions/game**, generating **$1,900.00/game** in physical product.
- **Displaced Opportunity Cost (C7)**: **$1,632.50/game** (net after subtracting $25.00/action displaced wheat watering value).

---

## 2. Seven-Category Decomposition of Missed Animal Care

| Category | Description | Engine Mechanism | Actions / Game | Realizable $/Game |
| :--- | :--- | :--- | :---: | :---: |
| **C1 — Realizable Missed Care** | Care not done, but animal fed, future prod exists, capacity fits, harvestable | Incremental +1 milk ($160) or wool ($200) realized | **10.70** | **+$1,900.00** |
| **C2 — No Future Production** | Day 29 or animal's next production is after season end (Day $\ge 30$) | Production refresh at Day 30 is unharvestable | 0.95 | $0.00 |
| **C3 — Unfed-Day Care** | Animal was not fed today | Line 829: `if cared and fed: pending += 1`. Unfed care banks 0 bonus | 3.00 | $0.00 |
| **C4 — Held-Product Cap Full** | Animal already holds $\ge 6$ units or `yield + base + pending >= max_held` | Line 827: `min(6, yield + base + bonus)` clips surplus to 0 | 0.15 | $0.00 |
| **C5 — Harvest Realization Constrained** | Product created but shed/time capacity prevents sale | Unharvested or unsold at Day 29 midnight | 0.00 | $0.00 |
| **C6 — Sufficient Care Bank** | `pending_care_bonus` already reached cycle cap (`interval`) | Extra care within same interval yields no additional output | 6.25 | $0.00 |
| **C7 — Displaced by Lower-Value Task** | Primary P3.2 target: realizable care displaced by routine wheat water | Worker did routine water ($25) instead of care ($160–$200) | **10.70** | **+$1,632.50** (Net) |

---

## 3. Reconciling the Static $3,926 Loss Estimate

The original $3,926.00/game static audit figure overstated the true recoverable prize by **51.6%** due to four structural engine realities:
1. **Unfed Days ($480.00/game overstatement)**: 3.0 animals/day miss feeding. In the engine, caring an unfed animal banks zero bonus.
2. **Cycle Bonus Saturation ($1,000.00/game overstatement)**: Cow interval is 2 days; sheep interval is 3 days. Once `pending_care_bonus` reaches 2 (Cow) or 3 (Sheep), subsequent care passes within the same production cycle produce zero incremental product.
3. **Endgame Cutoff ($152.00/game overstatement)**: On Day 28 and 29, care actions produce bonuses for Day 30+, which cannot be harvested.
4. **Displaced Task Value ($267.50/game opportunity cost)**: Executing CARE consumes 1 worker action, which displaces routine watering (+1 wheat = $25).

The **true, mathematically achievable ceiling** for P3.2 is **+$1,632.50/game** (Net C7).
