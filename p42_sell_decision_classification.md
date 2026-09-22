# Kaggriculture P4.2 Phase 5 & 6 Audit: Sell Decision Classification (M1–M9) & Causal Counterfactuals

## 1. Classification Taxonomy & Ground-Truth Distribution

Every market order in the 100-game ground-truth dataset (25,463 transactions) was classified into the M1–M9 taxonomy:

| Category | Description | Transactions | % of Total | Realized Revenue / Game | Recoverable Final Cash Potential |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **M1** | **Near-Optimal Sale** (Post-drain window, safe drip slice, high realized price) | **15,468** | **60.7%** | **$95,251.21** | **$0.00** (Already optimal) |
| **M2** | **Off-Window Sale / Emergency Relief** (Bypassed 4h window to relieve shed pressure) | **5,688** | **22.3%** | **$44,292.50** | **~$15.00** (Holding risks overflow) |
| **M8** | **Liquidity-Constrained Early Sale** (Days 0–9 sales required to fund hiring/seeds) | **4,016** | **15.8%** | **$7,025.35** | **$0.00** (Capital necessity) |
| **M3** | **Oversized Sale / Self-Glut** (Single slice experienced $>10\%$ marginal slippage) | **283** | **1.1%** | **$1,107.95** | **~$25.00** |
| **M4** | **Excessive Hold** (Held product until sold at floor price $\le \$1.50$ in endgame) | **8** | **0.0%** | **$0.59** | **~$5.00** |
| **M5** | **Opponent Preemption Failure** (Opponent dumped product concurrently) | **0** | **0.0%** | **$0.00** | **$0.00** |
| **M6** | **Order-Cap Displacement** (Sell truncated or rejected by 10-order cap) | **0** | **0.0%** | **$0.00** | **$0.00** |
| **M7** | **Inventory Unavailable** (Product still in worker hands) | N/A | — | — | Labor/transit constraint |
| **M9** | **Hindsight-Only Opportunity** (Unpredictable random shop unlock price spikes) | N/A | — | — | **$0.00** (Strictly non-actionable) |
| **TOTAL** | | **25,463** | **100.0%** | **$147,677.60** | **~$45.00 / game** |

---

## 2. Deep Dive: Causal Counterfactual Analysis

### A. Category M2: Off-Window Sales (22.3% of txs, $44.3k/game)
- **Observed Behavior**: Orders emitted at hours other than 1, 5, 9, 13, 17, 21. These occur almost exclusively during:
  1. Day 28–29 Endgame Liquidation (selling on every turn to guarantee complete cash realization).
  2. Soft-Cap Emergency Relief when `shed_total >= 65` or `pending_occupancy > 100`.
- **Feasible Counterfactual**: What if the agent strictly held these goods until the next post-drain window?
  - *Gross Price Uplift*: Waiting 1–3 hours for the next window would yield an estimated +$1.20/unit on ~25 off-window units per game = **+$30.00/game**.
  - *Downstream Capacity Risk*: When the shed is at 65+ units, incoming workers carrying strawberry, melon, or wool cannot deposit their loads. If a worker cannot deposit at EOD, units exceeding the 100 shed cap are **permanently destroyed by the engine**.
  - Losing even a single unit of strawberry ($240) or melon ($250) completely destroys 8 games of holding gains.
- **Causal Net Value**: Holding inventory under shed pressure produces a **negative expected value** due to overflow risk.

### B. Category M8: Liquidity-Constrained Early Sales (15.8% of txs, $7.0k/game)
- **Observed Behavior**: Selling early wheat and milk on Days 2–9 at prevailing spot prices ($30–$35 for wheat, $220–$240 for milk).
- **Feasible Counterfactual**: What if the agent held early wheat to wait for Day 15+ prices ($38–$40)?
  - *Capital Starvation*: On Days 1–6, the agent hires Hands 1 through 7 (Fibonacci costs: $1, $1, $2, $3, $5, $8, $13, $21, $34...) and purchases wheat/carrot seeds.
  - Delaying the sale of 10 wheat ($300) on Day 3 would prevent hiring Hand 5 and Hand 6 on schedule, losing dozens of worker-turns of watering and cultivation.
- **Causal Net Value**: $0.00. The early cash is worth orders of magnitude more in production velocity than the $5–$10 marginal price difference.

### C. Category M3: Oversized Sale / Self-Glut (1.1% of txs, $1.1k/game)
- **Observed Behavior**: Out of 25,463 orders, only 283 orders experienced slippage $>10\%$. These were primarily Day 29 emergency clear-outs or wheat flushes.
- **Feasible Counterfactual**: Restrict slice sizes to smaller tranches on Day 28.
  - Slicing smaller preserves ~$2.00/unit on ~15 units per game = **+$30.00/game**.
  - However, slicing smaller leaves inventory in the shed entering Day 29, compressing the final liquidation window.
- **Causal Net Value**: Feasible upside is capped at **+$20 to +$30/game**.

---

## 3. Synthesis & Non-Hindsight Opportunity Ceiling

When all downstream consequences, liquidity requirements, and storage risks are properly accounted for:
$$\text{Total Recoverable Non-Hindsight Market Opportunity} \le \mathbf{+\$45.00 \text{ to } +\$65.00 / \text{game}}$$

Compared to the game score standard deviation of **$8,724.54/game**, this opportunity represents **less than 0.75% of game noise**.
