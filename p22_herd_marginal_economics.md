# Kaggriculture P2.2: Herd Marginal Economics and Livestock Valuation

## Executive Summary

This audit establishes the actual marginal economics of the livestock enterprise under True Production Control (`237cf5ee54498ed1ad2fa04d00ad9a0ebd27352e`, `QUADRANT_HARD_BLOCK={4}`) across 100 matched cases (200 live games).

### Key Findings
1. **The Herd Reaches Exactly 10 Animals**: Across all games, the agent buys exactly **10 animals** (typically 7–8 Cows and 2–3 Sheep; Geese = 0), completely filling the available NW+NE pasture housing capacity.
2. **Gross Revenue Generated**: The livestock enterprise generates an average of **~$39,900.00** per game in realized product sales:
   - **Milk**: 144.6 units sold at ~$140/unit = **~$20,244.00**
   - **Wool**: 69.0 units sold at ~$190/unit = **~$13,110.00**
   - **Fertilizer**: 187.2 units sold at ~$35/unit = **~$6,552.00**
3. **Animal Purchase & Housing Capital**:
   - Total animal purchase spend: **$3,783.00** per game.
   - Housing construction: Pastures are built on dedicated non-tillable/fallow core tiles (e.g. NW `(4,4)`, `(4,5)` and NE near shed), costing negligible capital ($100 per pasture) and zero prime tillable crop tile displacement.
4. **Actual Physical Feed Incurred**:
   - The herd is fed for ~20 calendar days (Days 8/10 through Day 28).
   - Total physical feed consumed: **~204.8 units of wheat**.
   - At the baseline market wheat value of $25/unit, the true physical feed cost is **~$5,120.00**.
5. **Net Operating Contribution**:
   $$\text{Realized Product Revenue } (\$39,900) - \text{Animal Capital } (\$3,783) - \text{True Physical Feed } (\$5,120) - \text{Pasture Build } (\$400) = \mathbf{+\$30,597.00}$$
   **The livestock enterprise is overwhelmingly profitable**, delivering over **$30,500 in net profit** to the farm!
6. **The Apparent "Feed Deficit" Is An Accounting Mirage**:
   - The reported $21,489.25 wheat spend is **not** the true cost of feeding the herd.
   - Over 50% ($10,800) is Day 28 wash trading (buying and immediately dumping 432 units of wheat).
   - Another ~$5,000 is mid-season churn caused by `MarketBrain` selling self-grown wheat above a 4-day buffer, which forces `MacroPlanner` to buy it back.
   - Restricting animal purchases to reduce feed costs would destroy the most lucrative enterprise on the farm!

---

## 1. Species Ground Truth Parameters (Engine Rules)

| Species | Purchase Cost | Space Req | Structure | Cycle Interval | Base Yield | Max Held | Product | Base Price ($I_0=10k$) |
|---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **COW** | **$400** | 4 | PASTURE | 2 days (starts Day 8) | 1 unit + 1 care | 6 units | MILK | **$150** |
| **SHEEP** | **$500** | 4 | PASTURE | 3 days (starts Day 6) | 1 unit + 1 care | 6 units | WOOL | **$200** |
| **GOOSE** | $300 | 1 | COOP | 1 day (starts Day 4) | 1 unit + 1 care | 4 units | EGG | $60 |

- **Daily Feeding**: Every animal consumes 1 unit of `WHEAT` per day via `FEED` action.
- **Fertilizer Bonus**: Every fed animal produces 1 unit of `FERTILIZER` daily (collectible via `COLLECT_FERTILIZER`, sold for ~$35–$40 or used on crops).
- **Care Bonus**: A `CARE` action yields +1 unit of product on the next fed production day.

---

## 2. Incremental Lifecycle Economics: Cow vs. Sheep

### A. Marginal Cow (Purchased on Day 8, placed in existing pasture)
- **Purchase Cost**: $400
- **Feed Consumption**: Days 8–28 = 21 days $\times$ 1 wheat = 21 units wheat.
  - Valuation at self-grown wheat cost ($2.50 seed + labor): **$52.50**.
  - Valuation at market wheat price ($25.00): **$525.00**.
- **Labor Requirements**:
  - 21 `FEED` actions $\times$ $5 shadow cost = $105.
  - 10 `CARE` actions $\times$ $5 shadow cost = $50.
  - 10 `COLLECT_FERTILIZER` actions $\times$ $5 shadow cost = $50.
  - 4 `HARVEST` / collection actions $\times$ $5 shadow cost = $20.
  - Total labor shadow cost = **$225.00**.
- **Product Yield**:
  - Milk production days: Days 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28 (11 events).
  - With care: 2 units per event = 22 units of MILK.
  - Realized milk revenue: 22 units $\times$ ~$140 = **+$3,080.00**.
  - Fertilizer: ~18 units $\times$ ~$35 = **+$630.00**.
  - Gross Cow Revenue = **+$3,710.00**.
- **Net Cow Value**:
  - With self-grown wheat: $\$3,710 - \$400 - \$52.50 - \$225 = \mathbf{+\$3,032.50}$.
  - With market-bought wheat: $\$3,710 - \$400 - \$525.00 - \$225 = \mathbf{+\$2,560.00}$.

### B. Marginal Sheep (Purchased on Day 10, placed in existing pasture)
- **Purchase Cost**: $500
- **Feed Consumption**: Days 10–28 = 19 days $\times$ 1 wheat = 19 units wheat ($47.50 self-grown, $475 market).
- **Labor Requirements**: ~19 feeds + 6 cares + 10 ferts + 3 harvests = ~$190 shadow cost.
- **Product Yield**:
  - Wool production days: Days 10, 13, 16, 19, 22, 25, 28 (7 events).
  - With care: 2 units per event = 14 units of WOOL.
  - Realized wool revenue: 14 units $\times$ ~$190 = **+$2,660.00**.
  - Fertilizer: ~15 units $\times$ ~$35 = **+$525.00**.
  - Gross Sheep Revenue = **+$3,185.00**.
- **Net Sheep Value**:
  - With self-grown wheat: $\$3,185 - \$500 - \$47.50 - \$190 = \mathbf{+\$2,447.50}$.
  - With market-bought wheat: $\$3,185 - \$500 - \$475.00 - \$190 = \mathbf{+\$2,020.00}$.

---

## 3. Why Prior Livestock-Reduction Interventions Failed

In previous experiments (e.g. 2Q livestock serviceability cap and P1/P1.3):
- Restricting herd size reduced wheat purchases by ~110 units ($2,765/game) and reduced starvation animal-days by 37%.
- **However, final score dropped by -$317/game!**
- **Economic Reason**: Each cow or sheep prevented from being purchased saved ~$500 in feed, but forfeited **+$2,500 to +$3,000 in milk and wool revenue**.
- **Crucial Rule**: **Do NOT reduce herd size or livestock acquisition targets**. The animals are the highest-ROI assets on the farm.

---

## 4. Conclusion for P2.2

The problem is **not** that the agent has too many animals.
The problem is that the agent **buys wheat from the market that it does not need**, and **sells wheat to the market that its animals need**:
1. On Day 28, it wash-trades 432 units of wheat due to an endgame desynchronization.
2. On Days 0–27, it dumps self-grown wheat onto the market and then repurchases market wheat at an unfavorable bid-ask spread.
3. Aligning feed procurement and retention will capture thousands of dollars in pure margin without touching the herd.
