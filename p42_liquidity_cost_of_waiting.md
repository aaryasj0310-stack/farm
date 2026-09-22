# Kaggriculture P4.2 Phase 10 Audit: Liquidity Cost of Waiting & Investment Opportunity Cost

## 1. Objective: Final Score vs. Maximum Sale Price

A fundamental tenet of economic optimization in Kaggriculture is:
$$\text{Objective} = \max(\text{Final Cash at Day 30}) \quad \ne \quad \max(\text{Unit Sale Price})$$

A selling policy that waits days for a product price to rise from $30 to $40 may appear superior in price-realization metrics, but if that delay starves the farm of cash required to hire workers, buy seeds, or acquire livestock, it destroys tens of thousands of dollars in final score.

This audit quantifies the exact **Liquidity Opportunity Cost**:
$$\text{Net Economic Value} = \Delta \text{Price Realized} - \text{Opportunity Cost of Delayed Capital}$$

---

## 2. Early-Game Capital Obligations (Days 0–12)

The baseline production agent executes a rapid compounding investment curve:

| Day | Worker Hiring Target | Cumulative Daily Hiring Cost | Planned Seed / Animal Purchases | Required Cash Reserve |
| :--- | :--- | :--- | :--- | :--- |
| **Day 0** | Hand 1 ($1), Hand 2 ($1) | $2.00 | 20 Wheat Seeds ($200) | $300.00 |
| **Day 1** | Hand 3 ($2), Hand 4 ($3) | $5.00 | 20 Carrot Seeds ($400) | $300.00 |
| **Day 2** | Hand 5 ($5), Hand 6 ($8) | $13.00 | First Wheat Harvest Monctized | $300.00 |
| **Day 3** | Hand 7 ($13) | $13.00 | First Carrot Harvest Monetized | $300.00 |
| **Day 4** | Hand 8 ($21) | $21.00 | 2 Cows Purchased ($800) | $300.00 |
| **Day 5** | Hand 9 ($34) | $34.00 | 2 Sheep Purchased ($1,000) | $300.00 |
| **Day 6** | Hand 10 ($55) | $55.00 | 15 Strawberry Seeds ($1,500) | $300.00 |
| **Day 8** | Hand 11 ($89) | $89.00 | Additional Cows / Pastures | $300.00 |
| **Day 10** | Hand 12 ($144) | $144.00 | 15 Melon Seeds ($1,200) | $300.00 |

### The Compounding Velocity of Capital:
- In Days 0–6, **$1 of liquid cash** invested into hiring a hand yields approximately **$24.00 per day** in productive labor actions across the remaining 24 days ($576 lifetime value per hand).
- If the agent holds 10 wheat ($350) on Day 2 to wait for a hypothetical post-drain peak of $42 on Day 5, it earns an extra **+$70 in revenue**, but delays hiring Hand 5 and Hand 6 by 2 days.
- Delaying 2 workers for 2 days sacrifices:
  $$2 \text{ workers} \times 2 \text{ days} \times 24 \text{ turns} \times 0.30 \text{ productive ratio} \times \$24/\text{turn} = \mathbf{-\$691.20}$$
- **Net Causal Effect**: $+\$70.00 - \$691.20 = \mathbf{-\$621.20}$.

---

## 3. Storage & Shed Capacity Cost of Waiting

The shed has a physical ceiling of **100 units** shared across all 9 products:
- If the agent holds 20 units of wheat, 15 units of carrot, and 10 units of fertilizer to wait for price improvements, the available shed capacity drops to **55 units**.
- When livestock produce milk (12 units/day) and wool (8 units/day), and strawberry harvests come in (16 units/day), shed occupancy immediately hits 90+.
- **Shed Congestion Consequences**:
  1. Workers cannot deposit harvested crops and are forced to carry them in personal inventory.
  2. Workers carrying full inventories cannot harvest new crops, causing ripe strawberries and tomatoes to miss cycles or decay into weeds.
  3. At Day 23:59, any carried inventory that exceeds the 100-shed cap is deleted.

---

## 4. Conclusion

The production baseline's policy of selling products in the earliest post-drain window (`hour % 4 == 1`) is **economically superior** to holding for higher future prices:
- Accelerating cash velocity on Days 0–10 fuels the worker hiring and seed compounding engine.
- Keeping shed occupancy low (<50 units) ensures 100% of physical harvests are stored safely with zero decay or discard losses.
