# Kaggriculture P2.2: Feed Sourcing Opportunity Analysis and Bottleneck Diagnosis

## Executive Summary

This document evaluates the comparative economics of self-grown wheat versus market-purchased wheat (Phase D) and identifies the primary economic bottleneck governing feed procurement and livestock margins (Phase E).

---

## 1. Comparative Economics: Self-Grown vs. Market-Purchased Feed

### Economic Parameters per Unit of Wheat
| Dimension | Self-Grown Wheat | Market-Purchased Wheat |
|---|:---|:---|
| **Cash Cost** | $2.50 / unit ($10 seed / 4 yield) | **$25.00–$28.00 / unit** (market spot + price impact) |
| **Labor Requirement** | 1 planting + 4 waterings + 1 harvest = 6 actions / 4 units = 1.5 actions/unit (~$7.50 shadow labor) | **0 actions to grow** (executed in market phase without worker travel) |
| **All-In Economic Cost** | **$10.00 / unit** (Cash + Labor) | **$25.00–$28.00 / unit** (Pure Cash) |
| **Feed Value (Avoided Purchase)** | **+$25.00 / unit** | N/A (this IS the purchase) |
| **Net Value when Fed** | **+$15.00 / unit surplus** | **$0.00 surplus** (break-even feed) |
| **Net Value when Sold to Town** | **+$15.00 / unit surplus** ($25 sale - $10 cost) | **-$2.00 to -$3.00 loss** ($25 purchase $\rightarrow$ $23 sale) |

### Key Insight
- Self-grown wheat costs **$2.50 in cash** ($10 all-in with labor).
- Purchasing wheat from the market costs **$25.00+ in pure liquid treasury cash**.
- **Every unit of self-grown wheat fed to an animal saves the farm $22.50 in liquid cash** compared to buying that unit from the market.
- Conversely, selling self-grown wheat to the market for $25 and then buying wheat from the market for $25+ creates zero profit and subjects the farm to market order caps, transaction fees, and adverse price slippage.

---

## 2. Tile Opportunity Cost Analysis

On the core NW+NE tiles, what is the best use of tillable soil?

| Activity | Cycle Length | Seed Cost | Yield Units | Gross Revenue / Value | Total Labor Actions | Net Value / Cycle | Net Value / Day / Tile |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Wheat (Fed to Animals)** | 4 days | $10 | 4 units | **$100.00** (avoids 4 $\times$ $25 purchases) | 6 actions ($30) | **+$60.00** | **+$15.00 / day** |
| **Wheat (Sold to Market)** | 4 days | $10 | 4 units | **$100.00** (4 $\times$ $25 spot) | 7 actions ($35) | **+$55.00** | **+$13.75 / day** |
| **Carrot (Sold to Market)** | 4 days | $10 | 2 units | **$70.00** (2 $\times$ $35 spot) | 6 actions ($30) | **+$30.00** | **+$7.50 / day** |
| **Tomato (Sold to Market)** | 12 days | $40 | 5 units | **$300.00** (5 $\times$ $60 spot) | 16 actions ($80) | **+$180.00** | **+$15.00 / day** |
| **Strawberry (Days 3–13)** | 16 days | $100 | 6 units | **$720.00** (6 $\times$ $120 spot) | 23 actions ($115)| **+$505.00** | **+$31.50 / day** |
| **Fallow (Empty)** | — | $0 | 0 | $0.00 | 0 actions | **$0.00** | **$0.00 / day** |

### Findings
1. **Wheat fed to animals is the second-most profitable crop on the farm** ($15.00/day/tile), vastly outperforming Carrots ($7.50/day/tile).
2. **Strawberry is the only crop superior to Wheat** ($31.50/day/tile), which is why the farm correctly prioritizes Strawberry on Days 3–13 for its maximum cap (16–20 tiles).
3. The remaining ~25–30 tillable tiles on NW+NE are already dedicated to Wheat (average **107.7 wheat tiles planted per game**).
4. **The farm does NOT need more wheat tiles**. 107.7 wheat tiles produce ~500 units of wheat, which is 2.5× the herd's lifetime feed requirement (204.8 units).

---

## 3. Bottleneck Identification (Phase E)

We systematically evaluate the six potential hypotheses:

| Candidate Bottleneck | Verdict | Empirical Evidence |
|---|:---:|:---|
| **A. Excessive Feed-Buffer Purchasing** | **SUPPORTED (PRIMARY DEFECT)** | **50.3% of all wheat purchases ($10,800 / 432 units)** occur on Day 28 in a 22-hour wash trade. On Days 0–27, another ~$4,500 is spent due to buffer desynchronization between MacroPlanner and MarketBrain. |
| **B. Underproduction of Wheat** | **REFUTED** | The farm already produces **502.4 units of wheat per game**, while the herd only consumes **204.8 units**. Physical production is 250% of consumption. |
| **C. Overproduction of Wheat** | **REFUTED** | Wheat fed to animals delivers +$15.00/day/tile, and surplus wheat sold to town delivers +$13.75/day/tile, both beating Carrots ($7.50/day). Reducing wheat planting would lower overall revenue. |
| **D. Livestock Overinvestment** | **REFUTED** | The herd generates **+$39,900 in revenue** against **$3,783 purchase cost** and **$5,120 true feed cost**, netting **+$30,597**. Reducing animals drops score (as proven in the 2Q cap test). |
| **E. Feed Execution Inefficiency** | **PARTIALLY SUPPORTED** | Starvation days average 14.9 days/game, but this is caused by shed wheat being sold by MarketBrain rather than physical inability of workers to reach animals. |
| **F. No Significant Defect** | **REFUTED** | The $10,800 Day 28 circular wash trade is a severe, quantifiable capital leakage. |

---

## 4. The Exact Mechanism of the Day 28 Wash Trade

```
                 Day 28, Step Step Hour H (Hours 1..23)
                 ======================================

     [MacroPlanner]                              [MarketBrain / Liquidator]
     - Sees day = 28                             - Sees day = 28 (ENDGAME_START_DAY)
     - plan.feeding_enabled = True               - reserved_wheat = 0
     - wheat_buffer_target = 4                   - available_stock = all shed wheat
     - wheat_needed = 10 animals * 4 = 40        
     - shed wheat currently = 0                  
     - QUEUES: BUY_PRODUCT WHEAT 20              - QUEUES: SELL WHEAT 20
                 |                                           |
                 +---------------------+---------------------+
                                       |
                         [CentralPlanner / Market Phase]
                         - In 'shadow' mode, live reservation is OFF.
                         - Orders execute on market:
                           - Buys 20 wheat at $25+ (costs $500+)
                           - Sells 20 wheat at $24- (earns $480-)
                           - Net Capital Loss: ~$20–$50 per hour!
                         - Repeats 22 consecutive hours on Day 28!
                         - Total Day 28 Churn: 432 units bought ($10,800),
                           454 units sold ($10,896).
```

---

## 5. Strategic Prescription for P2.2

The single highest-value, cleanest, and most isolated intervention for P2.2 is:
**P2.2: Harmonized Feed Procurement & Endgame Wash-Trade Elimination**.

### The Minimal Isolated Intervention:
1. **Endgame Feed Horizon Clamping**:
   - On Day 28, only **1 day of feeding remains** (Day 28). Day 29 feeding is disabled by engine economics.
   - `wheat_needed` on Day 28 must be clamped to `n_animals × 1` (minus what was already fed today).
   - If shed wheat + fed today $\ge n_animals$, `buy_wheat` is strictly **0**.
2. **Prevent Buy/Sell Mutual Cancellation (Zero Wash Trades)**:
   - If `buy_wheat > 0` today, `MarketBrain` must not sell wheat.
   - If `EndgameLiquidator` is selling wheat, `MacroPlanner` must not buy wheat.
   - Clamp `MacroPlanner` wheat buying when `day >= ENDGAME_START_DAY`: never buy more than the actual unfed placed animals today.
3. **Mid-Game Feed Reservation Parity**:
   - Align `MarketBrain`'s `reserved_wheat` with `MacroPlanner`'s `wheat_needed`: `MarketBrain` must never sell wheat that `MacroPlanner` is actively trying to retain or buy.
