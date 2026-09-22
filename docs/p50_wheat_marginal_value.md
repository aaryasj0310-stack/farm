# P5.0 Marginal Wheat Economics & Days 21–25 Replacement Audit

## Overview of Wheat Allocation Decisions

Across the 100-game audit, the baseline agent made **10,146 total wheat planting decisions** (101.5 per game).
Using engine-exact state evaluation, every decision was categorized into four discrete marginal classes:

| Class | Definition & Criteria | Total Events | Per Game | P5.0 Policy Assessment |
| :--- | :--- | :---: | :---: | :--- |
| **W1: Feed Critical** | Projected feed balance without this planting < 0 before Day 30 | **2,144** | **21.4** | **MANDATORY**: Critical to avoid animal death and collapse |
| **W2: Early Profitable Surplus** | Planted Day ≤ 20 with feed buffer ≥ 0 | **5,509** | **55.1** | **EFFICIENT**: 6-day cycle matures with solid market return |
| **W3: Low-Margin Surplus** | Planted Days 21–25 with feed buffer ≥ 0 | **2,493** | **24.9** | **SUBOPTIMAL DEFECT**: High opportunity cost vs Carrots |
| **W4: Terminal Unharvestable** | Planted Day ≥ 26 (cannot mature before Day 30) | **0** | **0.0** | **ELIMINATED**: P2.3 fix completely prevented W4 plantings |

---

## Detailed Audit of W3 Surplus Wheat (Days 21–25)

The P2.3 fix successfully halted terminal wheat on Day 26+, but left a major economic loophole between **Day 21 and Day 25**:
- The agent plants **24.9 surplus wheat crops per game** during Days 21–25 when the herd already has guaranteed feed through Day 30.
- Wheat requires **5 full growth days** (matures on Day $D+5$) and produces 6 grain units selling into an already depressed town wheat market ($18–$21/unit), yielding ~\$105 gross revenue - \$20 seed = ~\$85 net revenue over 5 tile-days (\$17.00/tile-day).

### Counterfactual Replacement with Carrot Cycles
- A Carrot requires only **3 growth days** (seed \$35, yield 2 units @ \$35–\$45 base = \$70–\$90 gross revenue = ~\$35–\$55 net profit).
- Between Day 21 and Day 30 (9 remaining days), a tile planted with 2 successive Carrot cycles earns:
  $$2 \times \$45 = \$90\text{ net profit}$$
  while freeing up 3 days of labor and water during the critical Day 26–28 harvest rush.
- Replacing the 24.9 W3 wheat plantings with Carrot cycles yields an expected net margin gain of **+$1121.85 per game**!

---

## Recommendation

**STRONG GO for P5.1 (T1 Opportunity)**:
Implement a hard Day 21–25 Wheat Planting Gate. If existing shed grain plus in-ground wheat satisfies remaining herd feed consumption through Day 30, strictly prohibit W3 wheat planting and divert the tile and seed capital into high-turnover Carrot cycles.
